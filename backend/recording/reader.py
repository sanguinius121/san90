"""Sequential reader and validator for SAN-90 native RTA recordings."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import numpy as np
from numpy.typing import NDArray

from .format import (
    FILE_HEADER_SIZE,
    RECORD_PREFIX_SIZE,
    Crc32c,
    RecordingFormatError,
    unpack_file_header,
    unpack_known_record,
    unpack_record_prefix,
    validate_type_header_before_payload,
    verify_payload,
    verify_record_header,
)
from .models import (
    ConfigRecordFlags,
    ConfigurationRecord,
    EndFlags,
    EndRecord,
    GapRecord,
    GenericRecord,
    ParsedRecord,
    RecordType,
    SessionMetadataRecord,
    TraceBatchRecord,
    ValidationIssue,
    ValidationReport,
)


_READ_CHUNK_SIZE = 1024 * 1024


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = handle.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class San90RtaReader:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def read_header(self):
        with self.path.open("rb") as handle:
            return unpack_file_header(_read_exact(handle, FILE_HEADER_SIZE), offset=0)

    def _iter_records(self, *, verify_payload_crc: bool) -> Iterator[ParsedRecord]:
        with self.path.open("rb") as handle:
            file_header_bytes = _read_exact(handle, FILE_HEADER_SIZE)
            file_header = unpack_file_header(file_header_bytes, offset=0)
            rolling = Crc32c()
            rolling.update(file_header_bytes)
            handle.seek(file_header.first_record_offset)
            while True:
                offset = handle.tell()
                prefix_bytes = handle.read(RECORD_PREFIX_SIZE)
                if not prefix_bytes:
                    return
                prefix = unpack_record_prefix(prefix_bytes, offset=offset)
                type_header_bytes = _read_exact(handle, prefix.header_length - RECORD_PREFIX_SIZE)
                if len(type_header_bytes) != prefix.header_length - RECORD_PREFIX_SIZE:
                    raise RecordingFormatError(
                        "truncated_record_header",
                        f"record header requires {prefix.header_length} bytes",
                        offset=offset,
                        recoverable=True,
                    )
                header = prefix_bytes + type_header_bytes
                verify_record_header(prefix, header, offset=offset)
                validate_type_header_before_payload(prefix, header, offset=offset)

                is_known = prefix.record_version == 1 and prefix.record_type in {item.value for item in RecordType}
                computed_before = rolling.value if prefix.record_type == RecordType.END and prefix.record_version == 1 else None

                if is_known:
                    payload = _read_exact(handle, prefix.payload_length)
                    if len(payload) != prefix.payload_length:
                        raise RecordingFormatError(
                            "truncated_payload",
                            f"record payload requires {prefix.payload_length} bytes, found {len(payload)}",
                            offset=offset,
                            recoverable=True,
                        )
                    if verify_payload_crc:
                        verify_payload(prefix, payload, offset=offset)
                    rolling.update(header)
                    rolling.update(payload)
                    yield unpack_known_record(
                        prefix,
                        header,
                        payload,
                        offset=offset,
                        computed_rolling_crc32c=computed_before,
                    )
                    continue

                payload_checksum = Crc32c()
                remaining = prefix.payload_length
                rolling.update(header)
                while remaining:
                    chunk = handle.read(min(remaining, _READ_CHUNK_SIZE))
                    if not chunk:
                        raise RecordingFormatError(
                            "truncated_payload",
                            f"record payload is truncated with {remaining} bytes missing",
                            offset=offset,
                            recoverable=True,
                        )
                    remaining -= len(chunk)
                    rolling.update(chunk)
                    if verify_payload_crc:
                        payload_checksum.update(chunk)
                if verify_payload_crc:
                    computed_payload_crc = payload_checksum.value if prefix.payload_length else 0
                    if computed_payload_crc != prefix.payload_crc32c:
                        raise RecordingFormatError(
                            "payload_crc",
                            (
                                f"payload CRC32C mismatch: stored 0x{prefix.payload_crc32c:08x}, "
                                f"computed 0x{computed_payload_crc:08x}"
                            ),
                            offset=offset,
                            checksum_kind="payload",
                        )
                yield GenericRecord(offset, prefix)

    def iter_records(self) -> Iterator[ParsedRecord]:
        yield from self._iter_records(verify_payload_crc=True)

    def iter_configurations(self) -> Iterator[ConfigurationRecord]:
        for record in self.iter_records():
            if isinstance(record, ConfigurationRecord):
                yield record

    def iter_trace_batches(self) -> Iterator[TraceBatchRecord]:
        for record in self.iter_records():
            if isinstance(record, TraceBatchRecord):
                yield record

    def _find_configuration(self, config_id: int) -> ConfigurationRecord:
        for config in self.iter_configurations():
            if config.config_id == config_id:
                return config
        raise ValueError(f"trace references unknown config_id {config_id}")

    def reconstruct_dbm(self, batch: TraceBatchRecord, trace_index: int) -> NDArray[np.float32]:
        if not 0 <= trace_index < batch.trace_count:
            raise IndexError(f"trace_index {trace_index} is outside 0..{batch.trace_count - 1}")
        config = self._find_configuration(batch.config_id)
        if config.configuration_generation != batch.configuration_generation:
            raise ValueError("trace generation does not match referenced configuration")
        if config.frame_width != batch.frame_width:
            raise ValueError("trace frame width does not match referenced configuration")
        raw = batch.raw_traces()[trace_index]
        result = raw.astype(np.float32, copy=True)
        np.multiply(result, np.float32(config.hardware_scale_db_per_code), out=result)
        np.add(result, np.float32(config.hardware_offset_dbm), out=result)
        np.add(result, np.float32(config.software_amplitude_offset_db), out=result)
        return result

    def reconstruct_frequency_axis(self, batch: TraceBatchRecord) -> NDArray[np.float64]:
        config = self._find_configuration(batch.config_id)
        if not ConfigRecordFlags(config.prefix.flags) & ConfigRecordFlags.OUTER_BIN_EDGES:
            raise ValueError("configuration does not define the version-1 outer-bin-edge mapping")
        if config.frame_width != batch.frame_width:
            raise ValueError("trace frame width does not match referenced configuration")
        spacing = (config.stop_frequency_hz - config.start_frequency_hz) / config.frame_width
        return config.start_frequency_hz + (np.arange(config.frame_width, dtype=np.float64) + 0.5) * spacing

    def validate(self, *, verify_payload_crc: bool = True) -> ValidationReport:
        file_size = self.path.stat().st_size
        report = ValidationReport(path=str(self.path), file_size=file_size)
        is_part = self.path.name.endswith(".san90rta.part") or self.path.suffix == ".part"
        try:
            report.file_header = self.read_header()
        except (OSError, RecordingFormatError) as error:
            self._add_exception(report, error, is_part=is_part)
            return report

        expected_record_index = 1
        session_count = 0
        configs: dict[int, ConfigurationRecord] = {}
        last_config_id = 0
        expected_sequence: int | None = None
        pending_gap: GapRecord | None = None
        end_record: EndRecord | None = None

        try:
            for record in self._iter_records(verify_payload_crc=verify_payload_crc):
                report.record_count += 1
                if record.prefix.record_index != expected_record_index:
                    report.add_issue(
                        ValidationIssue(
                            "record_index",
                            f"expected record index {expected_record_index}, found {record.prefix.record_index}",
                            record.offset,
                        )
                    )
                expected_record_index = record.prefix.record_index + 1

                if end_record is not None:
                    report.add_issue(
                        ValidationIssue("record_after_end", "record appears after END", record.offset)
                    )
                    break

                if isinstance(record, SessionMetadataRecord):
                    session_count += 1
                    if session_count == 1:
                        report.session_metadata = record.metadata
                    else:
                        report.add_issue(
                            ValidationIssue("duplicate_session", "more than one session metadata record", record.offset)
                        )
                    continue

                if isinstance(record, ConfigurationRecord):
                    if record.config_id <= last_config_id:
                        report.add_issue(
                            ValidationIssue(
                                "config_id_order",
                                f"config_id {record.config_id} is not greater than {last_config_id}",
                                record.offset,
                            )
                        )
                    if record.config_id in configs:
                        report.add_issue(
                            ValidationIssue("duplicate_config_id", f"duplicate config_id {record.config_id}", record.offset)
                        )
                    last_config_id = max(last_config_id, record.config_id)
                    configs[record.config_id] = record
                    report.configurations.append(record)
                    report.config_record_count += 1
                    continue

                if isinstance(record, GapRecord):
                    report.gap_count += 1
                    report.lost_trace_count += record.estimated_lost_trace_count
                    if expected_sequence is not None and record.expected_sequence != expected_sequence:
                        report.add_issue(
                            ValidationIssue(
                                "gap_expected_sequence",
                                (
                                    f"gap expects sequence {record.expected_sequence}, "
                                    f"but trace continuity expects {expected_sequence}"
                                ),
                                record.offset,
                            )
                        )
                    pending_gap = record
                    report.discontinuities.append(
                        {
                            "kind": "gap",
                            "record_index": record.prefix.record_index,
                            "expected_sequence": record.expected_sequence,
                            "next_sequence": record.next_sequence,
                            "lost_trace_count": record.estimated_lost_trace_count,
                        }
                    )
                    continue

                if isinstance(record, TraceBatchRecord):
                    if session_count != 1:
                        report.add_issue(
                            ValidationIssue(
                                "session_before_trace",
                                "exactly one session metadata record must precede trace data",
                                record.offset,
                            )
                        )
                    config = configs.get(record.config_id)
                    if config is None:
                        report.add_issue(
                            ValidationIssue(
                                "missing_config",
                                f"trace references missing config_id {record.config_id}",
                                record.offset,
                            )
                        )
                    else:
                        if record.configuration_generation != config.configuration_generation:
                            report.add_issue(
                                ValidationIssue(
                                    "generation_mismatch",
                                    "trace generation does not match referenced configuration",
                                    record.offset,
                                )
                            )
                        if record.frame_width != config.frame_width:
                            report.add_issue(
                                ValidationIssue(
                                    "frame_width_mismatch",
                                    "trace frame width does not match referenced configuration",
                                    record.offset,
                                )
                            )
                    if expected_sequence is not None and record.first_sequence != expected_sequence:
                        explained = pending_gap is not None and pending_gap.next_sequence == record.first_sequence
                        if not explained:
                            report.add_issue(
                                ValidationIssue(
                                    "sequence_discontinuity",
                                    f"expected sequence {expected_sequence}, found {record.first_sequence}",
                                    record.offset,
                                )
                            )
                            report.discontinuities.append(
                                {
                                    "kind": "unexplained",
                                    "record_index": record.prefix.record_index,
                                    "expected_sequence": expected_sequence,
                                    "next_sequence": record.first_sequence,
                                    "lost_trace_count": max(0, record.first_sequence - expected_sequence),
                                }
                            )
                    elif pending_gap is not None and pending_gap.next_sequence != record.first_sequence:
                        report.add_issue(
                            ValidationIssue(
                                "gap_next_sequence",
                                (
                                    f"gap declares next sequence {pending_gap.next_sequence}, "
                                    f"found {record.first_sequence}"
                                ),
                                record.offset,
                            )
                        )
                    pending_gap = None
                    if report.first_sequence is None:
                        report.first_sequence = record.first_sequence
                    report.last_sequence = record.first_sequence + record.trace_count - 1
                    expected_sequence = report.last_sequence + 1
                    report.trace_batch_count += 1
                    report.trace_count += record.trace_count
                    report.raw_sample_count += record.prefix.payload_length
                    continue

                if isinstance(record, EndRecord):
                    end_record = record
                    report.end_record = record
                    report.complete = True
                    report.clean_finalization = bool(record.end_flags & EndFlags.CLEAN_FINALIZATION)
                    self._validate_end(report, record)
                    end_offset = record.offset + record.prefix.total_record_length
                    if end_offset != file_size:
                        report.add_issue(
                            ValidationIssue(
                                "record_after_end",
                                f"{file_size - end_offset} bytes appear after END",
                                end_offset,
                            )
                        )
                    break
        except (OSError, RecordingFormatError) as error:
            self._add_exception(report, error, is_part=is_part)

        if session_count != 1:
            report.add_issue(
                ValidationIssue(
                    "session_count",
                    f"expected exactly one session metadata record, found {session_count}",
                    FILE_HEADER_SIZE,
                    recoverable=is_part,
                )
            )
        if end_record is None:
            report.add_issue(
                ValidationIssue(
                    "missing_end",
                    "recording has no END record",
                    file_size,
                    recoverable=is_part,
                )
            )
        elif not report.clean_finalization:
            report.add_issue(
                ValidationIssue("unclean_end", "END record does not set clean-finalization", end_record.offset)
            )
        report.recoverable = report.recoverable or (is_part and report.file_header is not None)
        return report

    @staticmethod
    def _validate_end(report: ValidationReport, end: EndRecord) -> None:
        expected = {
            "total_record_count": report.record_count,
            "trace_batch_count": report.trace_batch_count,
            "trace_count": report.trace_count,
            "raw_sample_count": report.raw_sample_count,
            "bytes_before_end": end.offset,
            "final_file_bytes": end.offset + end.prefix.total_record_length,
            "gap_count": report.gap_count,
            "lost_trace_count": report.lost_trace_count,
            "config_record_count": report.config_record_count,
        }
        for field_name, expected_value in expected.items():
            actual_value = getattr(end, field_name)
            if actual_value != expected_value:
                report.add_issue(
                    ValidationIssue(
                        "end_counter_mismatch",
                        f"END {field_name}={actual_value}, observed {expected_value}",
                        end.offset,
                    )
                )
        if end.computed_rolling_crc32c != end.rolling_crc32c:
            report.add_issue(
                ValidationIssue(
                    "rolling_crc",
                    (
                        f"END rolling CRC32C=0x{end.rolling_crc32c:08x}, "
                        f"computed 0x{(end.computed_rolling_crc32c or 0):08x}"
                    ),
                    end.offset,
                    checksum_kind="rolling",
                )
            )

    @staticmethod
    def _add_exception(report: ValidationReport, error: Exception, *, is_part: bool) -> None:
        if isinstance(error, RecordingFormatError):
            issue = ValidationIssue(
                error.code,
                str(error),
                error.offset,
                recoverable=is_part and report.file_header is not None,
                checksum_kind=error.checksum_kind,
            )
        else:
            issue = ValidationIssue("io_error", str(error), recoverable=False)
        report.add_issue(issue)
