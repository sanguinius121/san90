"""Streaming structural index for clean version-1 recordings."""

from __future__ import annotations

import os
from pathlib import Path

from backend.recording.format import (
    END_RECORD_HEADER_SIZE,
    FILE_HEADER_SIZE,
    GAP_HEADER_STRUCT,
    RECORD_PREFIX_SIZE,
    TRACE_HEADER_STRUCT,
    RecordingFormatError,
    unpack_file_header,
    unpack_known_record,
    unpack_record_prefix,
    validate_type_header_before_payload,
    verify_payload,
    verify_record_header,
)
from backend.recording.models import (
    ConfigurationRecord,
    EndFlags,
    EndRecord,
    GapRecord,
    RecordType,
    SessionMetadataRecord,
    TimingFlags,
)

from .models import IndexedGap, IndexedTraceBatch, PlaybackIndex


def _read_exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise RecordingFormatError("truncated_record", f"expected {size} bytes, found {len(data)}", offset=handle.tell() - len(data))
    return data


def build_playback_index(path: str | os.PathLike[str]) -> PlaybackIndex:
    """Index headers/config metadata only; native trace payloads are seek-skipped."""
    file_path = Path(path)
    if file_path.name.endswith(".part"):
        raise RecordingFormatError("incomplete_file", "Phase 1 playback rejects .part files", offset=0)
    file_size = file_path.stat().st_size
    configurations: dict[int, ConfigurationRecord] = {}
    batches: list[IndexedTraceBatch] = []
    gaps: list[IndexedGap] = []
    session_metadata = {}
    session_count = 0
    end: EndRecord | None = None
    first_batch_monotonic: int | None = None
    expected_record_index = 1
    expected_sequence: int | None = None
    pending_gap: GapRecord | None = None
    last_config_id = 0
    observed_traces = 0
    observed_lost = 0

    with file_path.open("rb") as handle:
        file_header = unpack_file_header(_read_exact(handle, FILE_HEADER_SIZE), offset=0)
        handle.seek(file_header.first_record_offset)
        while handle.tell() < file_size:
            offset = handle.tell()
            prefix_bytes = _read_exact(handle, RECORD_PREFIX_SIZE)
            prefix = unpack_record_prefix(prefix_bytes, offset=offset)
            if prefix.record_index != expected_record_index:
                raise RecordingFormatError("record_index", f"expected record index {expected_record_index}, found {prefix.record_index}", offset=offset)
            expected_record_index += 1
            type_header = _read_exact(handle, prefix.header_length - RECORD_PREFIX_SIZE)
            header = prefix_bytes + type_header
            verify_record_header(prefix, header, offset=offset)
            validate_type_header_before_payload(prefix, header, offset=offset)
            payload_offset = handle.tell()
            if payload_offset + prefix.payload_length > file_size:
                raise RecordingFormatError(
                    "truncated_payload",
                    f"record payload at offset {offset} extends beyond end of file",
                    offset=offset,
                )

            if prefix.record_version != 1:
                handle.seek(prefix.payload_length, os.SEEK_CUR)
                continue
            try:
                kind = RecordType(prefix.record_type)
            except ValueError:
                handle.seek(prefix.payload_length, os.SEEK_CUR)
                continue
            if end is not None:
                raise RecordingFormatError("record_after_end", "record appears after END", offset=offset)

            if kind in {RecordType.SESSION_METADATA, RecordType.CONFIG}:
                payload = _read_exact(handle, prefix.payload_length)
                verify_payload(prefix, payload, offset=offset)
                parsed = unpack_known_record(prefix, header, payload, offset=offset)
                if isinstance(parsed, SessionMetadataRecord):
                    session_count += 1
                    session_metadata = parsed.metadata
                elif isinstance(parsed, ConfigurationRecord):
                    if parsed.config_id in configurations:
                        raise RecordingFormatError("duplicate_config_id", f"duplicate config_id {parsed.config_id}", offset=offset)
                    if parsed.config_id <= last_config_id:
                        raise RecordingFormatError("config_id_order", "CONFIG IDs are not monotonically increasing", offset=offset)
                    configurations[parsed.config_id] = parsed
                    last_config_id = parsed.config_id
                continue

            if kind == RecordType.TRACE_BATCH:
                values = TRACE_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE)
                config_id, generation, first_sequence, trace_count, frame_width = values[:5]
                config = configurations.get(config_id)
                if config is None:
                    raise RecordingFormatError("missing_config", f"trace references missing config_id {config_id}", offset=offset)
                if config.configuration_generation != generation or config.frame_width != frame_width:
                    raise RecordingFormatError("config_mismatch", "trace generation/frame width does not match CONFIG", offset=offset)
                if expected_sequence is not None and first_sequence != expected_sequence:
                    if pending_gap is None or pending_gap.next_sequence != first_sequence:
                        raise RecordingFormatError(
                            "sequence_discontinuity",
                            f"expected sequence {expected_sequence}, found {first_sequence}",
                            offset=offset,
                        )
                elif pending_gap is not None and pending_gap.next_sequence != first_sequence:
                    raise RecordingFormatError("gap_next_sequence", "GAP next sequence does not match TRACE", offset=offset)
                pending_gap = None
                expected_sequence = first_sequence + trace_count
                observed_traces += trace_count
                host_monotonic = values[7]
                if first_batch_monotonic is None:
                    first_batch_monotonic = host_monotonic
                cumulative = max(0.0, (host_monotonic - first_batch_monotonic) / 1e9)
                batches.append(
                    IndexedTraceBatch(
                        prefix.record_index, offset, payload_offset, prefix.payload_length,
                        prefix.payload_crc32c, config_id, generation, first_sequence,
                        trace_count, frame_width, values[5], values[6], host_monotonic,
                        values[8], values[9], TimingFlags(values[11]), prefix.flags, cumulative,
                    )
                )
                handle.seek(prefix.payload_length, os.SEEK_CUR)
                continue

            payload = _read_exact(handle, prefix.payload_length)
            verify_payload(prefix, payload, offset=offset)
            parsed = unpack_known_record(prefix, header, payload, offset=offset)
            if isinstance(parsed, GapRecord):
                if expected_sequence is not None and parsed.expected_sequence != expected_sequence:
                    raise RecordingFormatError("gap_expected_sequence", "GAP expected sequence is inconsistent", offset=offset)
                pending_gap = parsed
                observed_lost += parsed.estimated_lost_trace_count
                base = first_batch_monotonic if first_batch_monotonic is not None else parsed.start_monotonic_ns
                gaps.append(IndexedGap(prefix.record_index, max(0.0, (parsed.end_monotonic_ns - base) / 1e9), parsed))
            elif isinstance(parsed, EndRecord):
                end = parsed
                if handle.tell() != file_size:
                    raise RecordingFormatError("record_after_end", "bytes appear after END", offset=handle.tell())
                break

    if session_count != 1:
        raise RecordingFormatError("session_count", f"expected one SESSION_METADATA record, found {session_count}", offset=FILE_HEADER_SIZE)
    if end is None:
        raise RecordingFormatError("missing_end", "recording has no END record", offset=file_size)
    if not end.end_flags & EndFlags.CLEAN_FINALIZATION:
        raise RecordingFormatError("unclean_end", "recording is not cleanly finalized", offset=end.offset)
    if end.prefix.header_length != END_RECORD_HEADER_SIZE:
        raise RecordingFormatError("invalid_end", "invalid END header", offset=end.offset)
    if (
        end.trace_batch_count != len(batches)
        or end.trace_count != observed_traces
        or end.config_record_count != len(configurations)
        or end.gap_count != len(gaps)
        or end.lost_trace_count != observed_lost
    ):
        raise RecordingFormatError("end_counter_mismatch", "END counters do not match playback index", offset=end.offset)
    duration_s = end.duration_ns / 1e9
    return PlaybackIndex(
        str(file_header.session_uuid), file_header.creation_unix_ns, session_metadata,
        configurations, tuple(batches), tuple(gaps), end, duration_s, file_size,
    )
