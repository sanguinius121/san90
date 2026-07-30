"""Strictly sequential production writer for version-1 SAN-90 RTA files."""

from __future__ import annotations

import os
import time
import errno
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .format import (
    CONFIG_HEADER_STRUCT,
    END_HEADER_STRUCT,
    END_RECORD_HEADER_SIZE,
    EVENT_HEADER_STRUCT,
    GAP_HEADER_STRUCT,
    TRACE_HEADER_STRUCT,
    Crc32c,
    canonical_json_bytes,
    crc32c,
    pack_file_header,
    pack_record_header,
)
from .models import (
    ConfigRecordFlags,
    EndFlags,
    EventCode,
    EventSeverity,
    GapFlags,
    GapReason,
    RecordingConfiguration,
    RecordType,
    StopReason,
    TimingFlags,
    TraceRecordFlags,
)
from .storage import RecordingStorage, StorageSession


class RecordingWriterError(OSError):
    pass


class San90RtaWriter:
    """A single-thread-owned writer; callers must serialize all operations."""

    def __init__(
        self,
        storage: RecordingStorage,
        session: StorageSession,
        *,
        session_uuid: UUID,
        creation_unix_ns: int,
        start_monotonic_ns: int,
        write_func: Callable[[int, bytes], int] = os.write,
    ) -> None:
        self.storage = storage
        self.session = session
        self.session_uuid = session_uuid
        self.creation_unix_ns = creation_unix_ns
        self.start_monotonic_ns = start_monotonic_ns
        self._write_func = write_func
        self._closed = False
        self._finalized = False
        self._record_index = 0
        self._rolling = Crc32c()
        self._configs: dict[int, tuple[int, int]] = {}
        self.written_bytes = 0
        self.total_record_count = 0
        self.trace_batch_count = 0
        self.trace_count = 0
        self.raw_sample_count = 0
        self.gap_count = 0
        self.lost_trace_count = 0
        self.config_record_count = 0
        self.last_write_latency_ms = 0.0
        header = pack_file_header(
            creation_unix_ns=creation_unix_ns,
            session_uuid=session_uuid,
        )
        self._write_complete(header)
        self._rolling.update(header)

    @classmethod
    def open_session(
        cls,
        storage: RecordingStorage,
        *,
        file_prefix: str,
        creation_unix_ns: int | None = None,
        start_monotonic_ns: int | None = None,
        session_uuid: UUID | None = None,
        write_func: Callable[[int, bytes], int] = os.write,
    ) -> "San90RtaWriter":
        identifier = session_uuid or uuid4()
        created = time.time_ns() if creation_unix_ns is None else creation_unix_ns
        started = time.monotonic_ns() if start_monotonic_ns is None else start_monotonic_ns
        session = storage.open_session(prefix=file_prefix, session_uuid=identifier, creation_unix_ns=created)
        try:
            return cls(
                storage,
                session,
                session_uuid=identifier,
                creation_unix_ns=created,
                start_monotonic_ns=started,
                write_func=write_func,
            )
        except BaseException as error:
            os.close(session.fd)
            try:
                setattr(error, "part_path", str(session.part_path))
            except (AttributeError, TypeError):
                pass
            raise

    @property
    def part_path(self) -> Path:
        return self.session.part_path

    @property
    def final_path(self) -> Path:
        return self.session.final_path

    @property
    def next_record_index(self) -> int:
        return self._record_index + 1

    def estimate_record_size(self, type_header_size: int, payload_size: int) -> int:
        return 48 + type_header_size + payload_size

    def write_session_metadata(self, metadata: Mapping[str, Any]) -> int:
        return self._write_record(RecordType.SESSION_METADATA, b"", canonical_json_bytes(metadata))

    def write_config(
        self,
        *,
        config_id: int,
        configuration: RecordingConfiguration,
        effective_first_sequence: int,
        effective_host_unix_ns: int,
        effective_host_monotonic_ns: int,
    ) -> int:
        if config_id in self._configs:
            raise ValueError(f"config_id {config_id} already exists")
        if self._configs and config_id <= max(self._configs):
            raise ValueError("config IDs must increase monotonically")
        finite = (
            configuration.center_frequency_hz, configuration.start_frequency_hz,
            configuration.stop_frequency_hz, configuration.span_hz, configuration.rbw_hz,
            configuration.reference_level_dbm, configuration.hardware_scale_db_per_code,
            configuration.hardware_offset_dbm, configuration.software_amplitude_offset_db,
        )
        if not all(math.isfinite(value) for value in finite):
            raise ValueError("configuration contains non-finite decode values")
        if (
            configuration.stop_frequency_hz <= configuration.start_frequency_hz
            or not math.isclose(
                configuration.span_hz,
                configuration.stop_frequency_hz - configuration.start_frequency_hz,
                rel_tol=1e-12,
                abs_tol=1e-3,
            )
            or configuration.rbw_hz <= 0
            or configuration.hardware_scale_db_per_code <= 0
            or configuration.frame_width < 2
        ):
            raise ValueError("configuration violates version-1 decode invariants")
        flags = ConfigRecordFlags.OUTER_BIN_EDGES
        if configuration.vbw_hz is not None:
            flags |= ConfigRecordFlags.VBW_VALID
        if configuration.sweep_time_s is not None:
            flags |= ConfigRecordFlags.SWEEP_TIME_VALID
        type_header = CONFIG_HEADER_STRUCT.pack(
            config_id,
            configuration.configuration_generation,
            effective_first_sequence,
            effective_host_unix_ns,
            effective_host_monotonic_ns,
            configuration.center_frequency_hz,
            configuration.start_frequency_hz,
            configuration.stop_frequency_hz,
            configuration.span_hz,
            configuration.rbw_hz,
            configuration.vbw_hz or 0.0,
            configuration.sweep_time_s or 0.0,
            configuration.reference_level_dbm,
            configuration.hardware_scale_db_per_code,
            configuration.hardware_offset_dbm,
            configuration.software_amplitude_offset_db,
            configuration.frame_width,
            configuration.fft_size,
        )
        payload = canonical_json_bytes(configuration.metadata) if configuration.metadata else b""
        size = self._write_record(RecordType.CONFIG, type_header, payload, flags=int(flags))
        self._configs[config_id] = (
            configuration.configuration_generation,
            configuration.frame_width,
        )
        self.config_record_count += 1
        return size

    def write_trace_batch(
        self,
        *,
        config_id: int,
        configuration_generation: int,
        first_sequence: int,
        trace_count: int,
        frame_width: int,
        device_packet_timestamp_ns: int,
        host_receipt_unix_ns: int,
        host_receipt_monotonic_ns: int,
        nominal_trace_period_ns: int,
        packet_acquisition_duration_ns: int,
        sdk_trace_timestamp_step_raw: float,
        timing_flags: TimingFlags,
        trace_flags: TraceRecordFlags,
        payload: bytes,
    ) -> int:
        expected = self._configs.get(config_id)
        if expected is None:
            raise ValueError(f"trace references unknown config_id {config_id}")
        if expected != (configuration_generation, frame_width):
            raise ValueError("trace generation/frame width does not match referenced config")
        if trace_count <= 0 or frame_width <= 0 or len(payload) != trace_count * frame_width:
            raise ValueError("trace payload length must equal positive trace_count * frame_width")
        type_header = TRACE_HEADER_STRUCT.pack(
            config_id,
            configuration_generation,
            first_sequence,
            trace_count,
            frame_width,
            device_packet_timestamp_ns,
            host_receipt_unix_ns,
            host_receipt_monotonic_ns,
            nominal_trace_period_ns,
            packet_acquisition_duration_ns,
            sdk_trace_timestamp_step_raw,
            int(timing_flags),
            0,
        )
        size = self._write_record(
            RecordType.TRACE_BATCH,
            type_header,
            payload,
            flags=int(trace_flags),
        )
        self.trace_batch_count += 1
        self.trace_count += trace_count
        self.raw_sample_count += len(payload)
        return size

    def write_gap(
        self,
        *,
        config_id: int,
        configuration_generation: int,
        expected_sequence: int,
        next_sequence: int,
        estimated_lost_trace_count: int,
        start_monotonic_ns: int,
        end_monotonic_ns: int,
        start_device_timestamp_ns: int = 0,
        end_device_timestamp_ns: int = 0,
        reason_code: GapReason,
        gap_flags: GapFlags,
        detail_code: int = 0,
    ) -> int:
        type_header = GAP_HEADER_STRUCT.pack(
            config_id,
            configuration_generation,
            expected_sequence,
            next_sequence,
            estimated_lost_trace_count,
            start_monotonic_ns,
            end_monotonic_ns,
            start_device_timestamp_ns,
            end_device_timestamp_ns,
            int(reason_code),
            int(gap_flags),
            detail_code,
        )
        size = self._write_record(RecordType.GAP, type_header, b"")
        self.gap_count += 1
        self.lost_trace_count += estimated_lost_trace_count
        return size

    def write_event(
        self,
        *,
        event_code: EventCode,
        severity: EventSeverity,
        event_unix_ns: int | None = None,
        event_monotonic_ns: int | None = None,
        config_id: int = 0,
        configuration_generation: int = 0,
        sequence: int = 0,
        details: Mapping[str, Any] | None = None,
    ) -> int:
        type_header = EVENT_HEADER_STRUCT.pack(
            time.time_ns() if event_unix_ns is None else event_unix_ns,
            time.monotonic_ns() if event_monotonic_ns is None else event_monotonic_ns,
            int(event_code),
            int(severity),
            0,
            config_id,
            configuration_generation,
            sequence,
        )
        payload = canonical_json_bytes(details) if details else b""
        return self._write_record(RecordType.EVENT, type_header, payload)

    def finalize(self, *, stop_reason: StopReason, details: Mapping[str, Any] | None = None) -> Path:
        if self._finalized:
            return self.final_path
        self._ensure_open()
        now_unix = time.time_ns()
        now_mono = time.monotonic_ns()
        self.write_event(
            event_code=_stop_event_code(stop_reason),
            severity=EventSeverity.ERROR if stop_reason in {StopReason.WRITER_ERROR, StopReason.START_FAILURE} else
            EventSeverity.WARNING if stop_reason in {
                StopReason.LOW_DISK, StopReason.FILE_SIZE_LIMIT, StopReason.WRITER_OVERRUN,
                StopReason.DEVICE_DISCONNECT,
            } else EventSeverity.INFO,
            event_unix_ns=now_unix,
            event_monotonic_ns=now_mono,
            details={"stop_reason": stop_reason.name.lower(), **(details or {})},
        )
        bytes_before_end = self.written_bytes
        final_file_bytes = bytes_before_end + END_RECORD_HEADER_SIZE
        type_header = END_HEADER_STRUCT.pack(
            now_unix,
            now_mono,
            int(stop_reason),
            int(EndFlags.CLEAN_FINALIZATION),
            0,
            self.total_record_count + 1,
            self.trace_batch_count,
            self.trace_count,
            self.raw_sample_count,
            bytes_before_end,
            final_file_bytes,
            self.gap_count,
            self.lost_trace_count,
            self.config_record_count,
            max(0, now_mono - self.start_monotonic_ns),
            self._rolling.value,
            0,
        )
        self._write_record(RecordType.END, type_header, b"", include_in_rolling=False)
        try:
            os.fsync(self.session.fd)
            os.close(self.session.fd)
            self._closed = True
            final_path = self.storage.finalize(self.session)
        except OSError as error:
            if not self._closed:
                try:
                    os.close(self.session.fd)
                except OSError:
                    pass
            self._closed = True
            raise RecordingWriterError(error.errno, f"finalize failed: {error}", str(self.part_path)) from error
        self._finalized = True
        return final_path

    def abort(self) -> None:
        if not self._closed:
            os.close(self.session.fd)
            self._closed = True

    def _write_record(
        self,
        record_type: RecordType,
        type_header: bytes,
        payload: bytes,
        *,
        flags: int = 0,
        include_in_rolling: bool = True,
    ) -> int:
        self._ensure_open()
        record_index = self.next_record_index
        payload_crc = crc32c(payload) if payload else 0
        header = pack_record_header(
            record_type=record_type,
            record_index=record_index,
            type_header=type_header,
            payload_length=len(payload),
            payload_crc32c=payload_crc,
            flags=flags,
        )
        started = time.perf_counter_ns()
        self._write_complete(header)
        if payload:
            self._write_complete(payload)
        self.last_write_latency_ms = (time.perf_counter_ns() - started) / 1e6
        if include_in_rolling:
            self._rolling.update(header)
            if payload:
                self._rolling.update(payload)
        self._record_index = record_index
        self.total_record_count += 1
        return len(header) + len(payload)

    def _write_complete(self, data: bytes) -> None:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            try:
                written = self._write_func(self.session.fd, view[offset:])
            except InterruptedError:
                continue
            except OSError as error:
                raise RecordingWriterError(error.errno, f"write failed: {error}", str(self.part_path)) from error
            if written <= 0:
                raise RecordingWriterError(errno.EIO, "write returned zero bytes", str(self.part_path))
            offset += written
            self.written_bytes += written

    def _ensure_open(self) -> None:
        if self._closed:
            raise RecordingWriterError(errno.EBADF, "writer is closed", str(self.part_path))


def _stop_event_code(reason: StopReason) -> EventCode:
    return {
        StopReason.USER_STOP: EventCode.USER_STOP_REQUESTED,
        StopReason.FIXED_DURATION: EventCode.FIXED_DURATION_REACHED,
        StopReason.FILE_SIZE_LIMIT: EventCode.FILE_SIZE_LIMIT_REACHED,
        StopReason.LOW_DISK: EventCode.LOW_DISK_STOP,
        StopReason.DEVICE_DISCONNECT: EventCode.DEVICE_DISCONNECTED,
    }.get(reason, EventCode.WRITER_ERROR if reason == StopReason.WRITER_ERROR else EventCode.WRITER_WARNING)
