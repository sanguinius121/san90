"""Semantic models for the SAN-90 RTA recording format."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, IntFlag
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

import numpy as np
from numpy.typing import NDArray


class RecordType(IntEnum):
    SESSION_METADATA = 0x0001
    CONFIG = 0x0002
    TRACE_BATCH = 0x0003
    GAP = 0x0004
    EVENT = 0x0005
    END = 0x00FF


class EventCode(IntEnum):
    RECORDING_STARTED = 1
    USER_STOP_REQUESTED = 2
    FIXED_DURATION_REACHED = 3
    FILE_SIZE_LIMIT_REACHED = 4
    LOW_DISK_STOP = 5
    DEVICE_DISCONNECTED = 6
    DEVICE_RECONNECTED = 7
    IF_OVERFLOW_ENTERED = 8
    IF_OVERFLOW_CLEARED = 9
    CONFIGURATION_CHANGED = 10
    WRITER_WARNING = 11
    WRITER_ERROR = 12


class EventSeverity(IntEnum):
    INFO = 1
    WARNING = 2
    ERROR = 3


class GapReason(IntEnum):
    QUEUE_OVERFLOW = 1
    SEQUENCE_DISCONTINUITY = 2
    RECONFIGURATION_PAUSE = 3
    DEVICE_DISCONNECT = 4
    WRITER_OVERRUN = 5
    UNKNOWN = 6


class StopReason(IntEnum):
    USER_STOP = 1
    FIXED_DURATION = 2
    FILE_SIZE_LIMIT = 3
    LOW_DISK = 4
    WRITER_OVERRUN = 5
    DEVICE_DISCONNECT = 6
    BACKEND_SHUTDOWN = 7
    WRITER_ERROR = 8
    START_FAILURE = 9


class RecordingMode(str, Enum):
    FIXED = "fixed"
    MANUAL = "manual"


class RecorderState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RECORDING = "recording"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class OfferResult(str, Enum):
    ACCEPTED = "accepted"
    REJECTED_QUEUE_FULL = "rejected_queue_full"
    REJECTED_STOPPING = "rejected_stopping"
    REJECTED_LIMIT = "rejected_limit"


class FileFlags(IntFlag):
    NONE = 0


class ConfigRecordFlags(IntFlag):
    NONE = 0
    VBW_VALID = 1 << 0
    SWEEP_TIME_VALID = 1 << 1
    OUTER_BIN_EDGES = 1 << 2


class TraceRecordFlags(IntFlag):
    NONE = 0
    SDK_IF_OVERFLOW = 1 << 0
    IF_OVERFLOW_LATCHED = 1 << 1


class GapFlags(IntFlag):
    NONE = 0
    LOSS_COUNT_EXACT = 1 << 0
    LOSS_COUNT_ESTIMATED = 1 << 1
    SEQUENCE_REGRESSED = 1 << 2
    PAUSE_WITHOUT_OBSERVED_LOSS = 1 << 3


class TimingFlags(IntFlag):
    NONE = 0
    DEVICE_TIMESTAMP_PRESENT = 1 << 0
    DEVICE_TIMESTAMP_HOST_EPOCH = 1 << 1
    PERIOD_FROM_PACKET_ACQUISITION = 1 << 2
    SDK_TIMESTAMP_STEP_UNITS_CONFIRMED = 1 << 3


class EndFlags(IntFlag):
    NONE = 0
    CLEAN_FINALIZATION = 1 << 0


@dataclass(frozen=True, slots=True)
class RecordingConfig:
    mode: RecordingMode
    output_directory: Path
    file_prefix: str = "SAN90_RTA"
    duration_s: float | None = None
    file_size_limit_bytes: int = 4 * 1024**3
    free_disk_reserve_bytes: int = 2 * 1024**3


@dataclass(frozen=True, slots=True)
class RecordingConfiguration:
    configuration_generation: int
    center_frequency_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float | None
    sweep_time_s: float | None
    reference_level_dbm: float
    hardware_scale_db_per_code: float
    hardware_offset_dbm: float
    software_amplitude_offset_db: float
    frame_width: int
    fft_size: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecordingPacket:
    configuration: RecordingConfiguration
    first_sequence: int
    trace_count: int
    device_packet_timestamp_ns: int
    host_receipt_unix_ns: int
    host_receipt_monotonic_ns: int
    nominal_trace_period_ns: int = 0
    packet_acquisition_duration_ns: int = 0
    sdk_trace_timestamp_step_raw: float = 0.0
    timing_flags: TimingFlags = TimingFlags.NONE
    trace_flags: TraceRecordFlags = TraceRecordFlags.NONE


@dataclass(frozen=True, slots=True)
class RecorderStatus:
    state: RecorderState
    session_uuid: str | None
    part_file_path: str | None
    final_file_path: str | None
    mode: RecordingMode | None
    elapsed_s: float
    written_bytes: int
    trace_count: int
    batch_count: int
    gap_count: int
    lost_trace_count: int
    queue_bytes: int
    queue_items: int
    queue_fill_ratio: float
    queue_item_fill_ratio: float
    queue_high_water_bytes: int
    queue_high_water_items: int
    enqueued_batches: int
    written_batches: int
    rejected_batches: int
    rejected_traces: int
    rejected_samples: int
    write_rate_bytes_s: float
    last_write_latency_ms: float
    stop_reason: StopReason | None
    last_error: str | None
    active_config_id: int | None = None
    active_configuration_generation: int | None = None

    @property
    def queue_pressure(self) -> str:
        fill = max(self.queue_fill_ratio, self.queue_item_fill_ratio)
        if fill >= 0.90:
            return "critical"
        if fill >= 0.70:
            return "warning"
        return "normal"


@dataclass(frozen=True, slots=True)
class FileHeader:
    format_major: int
    format_minor: int
    byte_order_marker: int
    header_length: int
    flags: FileFlags
    creation_unix_ns: int
    session_uuid: UUID
    record_prefix_length: int
    max_record_header_length: int
    first_record_offset: int
    max_record_length: int
    header_crc32c: int


@dataclass(frozen=True, slots=True)
class RecordPrefix:
    record_type: int
    record_version: int
    flags: int
    header_length: int
    payload_length: int
    record_index: int
    header_crc32c: int
    payload_crc32c: int
    total_record_length: int


@dataclass(frozen=True, slots=True)
class GenericRecord:
    offset: int
    prefix: RecordPrefix


@dataclass(frozen=True, slots=True)
class SessionMetadataRecord:
    offset: int
    prefix: RecordPrefix
    metadata: Mapping[str, Any]
    payload: bytes


@dataclass(frozen=True, slots=True)
class ConfigurationRecord:
    offset: int
    prefix: RecordPrefix
    config_id: int
    configuration_generation: int
    effective_first_sequence: int
    effective_host_unix_ns: int
    effective_host_monotonic_ns: int
    center_frequency_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    span_hz: float
    rbw_hz: float
    vbw_hz: float
    sweep_time_s: float
    reference_level_dbm: float
    hardware_scale_db_per_code: float
    hardware_offset_dbm: float
    software_amplitude_offset_db: float
    frame_width: int
    fft_size: int
    metadata: Mapping[str, Any]
    payload: bytes


@dataclass(frozen=True, slots=True)
class TraceBatchRecord:
    offset: int
    prefix: RecordPrefix
    config_id: int
    configuration_generation: int
    first_sequence: int
    trace_count: int
    frame_width: int
    device_packet_timestamp_ns: int
    host_receipt_unix_ns: int
    host_receipt_monotonic_ns: int
    nominal_trace_period_ns: int
    packet_acquisition_duration_ns: int
    sdk_trace_timestamp_step_raw: float
    timing_flags: TimingFlags
    payload: bytes

    def raw_traces(self) -> NDArray[np.uint8]:
        return np.frombuffer(self.payload, dtype=np.uint8).reshape(self.trace_count, self.frame_width)


@dataclass(frozen=True, slots=True)
class GapRecord:
    offset: int
    prefix: RecordPrefix
    config_id: int
    configuration_generation: int
    expected_sequence: int
    next_sequence: int
    estimated_lost_trace_count: int
    start_monotonic_ns: int
    end_monotonic_ns: int
    start_device_timestamp_ns: int
    end_device_timestamp_ns: int
    reason_code: GapReason | int
    gap_flags: GapFlags
    detail_code: int


@dataclass(frozen=True, slots=True)
class EventRecord:
    offset: int
    prefix: RecordPrefix
    event_unix_ns: int
    event_monotonic_ns: int
    event_code: EventCode | int
    severity: EventSeverity | int
    config_id: int
    configuration_generation: int
    sequence: int
    details: Mapping[str, Any]
    payload: bytes


@dataclass(frozen=True, slots=True)
class EndRecord:
    offset: int
    prefix: RecordPrefix
    stop_unix_ns: int
    stop_monotonic_ns: int
    stop_reason: StopReason | int
    end_flags: EndFlags
    total_record_count: int
    trace_batch_count: int
    trace_count: int
    raw_sample_count: int
    bytes_before_end: int
    final_file_bytes: int
    gap_count: int
    lost_trace_count: int
    config_record_count: int
    duration_ns: int
    rolling_crc32c: int
    computed_rolling_crc32c: int | None = None


ParsedRecord = (
    GenericRecord
    | SessionMetadataRecord
    | ConfigurationRecord
    | TraceBatchRecord
    | GapRecord
    | EventRecord
    | EndRecord
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    offset: int | None = None
    recoverable: bool = False
    checksum_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "offset": self.offset,
            "recoverable": self.recoverable,
            "checksum_kind": self.checksum_kind,
        }


@dataclass(slots=True)
class ValidationReport:
    path: str
    file_size: int
    file_header: FileHeader | None = None
    issues: list[ValidationIssue] = field(default_factory=list)
    session_metadata: Mapping[str, Any] | None = None
    end_record: EndRecord | None = None
    complete: bool = False
    clean_finalization: bool = False
    recoverable: bool = False
    first_invalid_offset: int | None = None
    record_count: int = 0
    trace_batch_count: int = 0
    trace_count: int = 0
    raw_sample_count: int = 0
    gap_count: int = 0
    lost_trace_count: int = 0
    config_record_count: int = 0
    configurations: list[ConfigurationRecord] = field(default_factory=list)
    first_sequence: int | None = None
    last_sequence: int | None = None
    discontinuities: list[dict[str, int | str]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if self.first_invalid_offset is None and issue.offset is not None:
            self.first_invalid_offset = issue.offset
        self.recoverable = self.recoverable or issue.recoverable

    def to_dict(self) -> dict[str, Any]:
        header = self.file_header
        end = self.end_record
        return {
            "path": self.path,
            "file_size": self.file_size,
            "valid": self.valid,
            "complete": self.complete,
            "clean_finalization": self.clean_finalization,
            "recoverable": self.recoverable,
            "first_invalid_offset": self.first_invalid_offset,
            "format_version": None if header is None else f"{header.format_major}.{header.format_minor}",
            "session_uuid": None if header is None else str(header.session_uuid),
            "creation_unix_ns": None if header is None else header.creation_unix_ns,
            "session_metadata": self.session_metadata,
            "stop_unix_ns": None if end is None else end.stop_unix_ns,
            "duration_ns": None if end is None else end.duration_ns,
            "stop_reason": None if end is None else _enum_name(end.stop_reason),
            "record_count": self.record_count,
            "trace_batch_count": self.trace_batch_count,
            "trace_count": self.trace_count,
            "raw_sample_count": self.raw_sample_count,
            "gap_count": self.gap_count,
            "lost_trace_count": self.lost_trace_count,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "discontinuities": self.discontinuities,
            "configurations": [
                {
                    "record_index": config.prefix.record_index,
                    "config_id": config.config_id,
                    "configuration_generation": config.configuration_generation,
                    "start_frequency_hz": config.start_frequency_hz,
                    "center_frequency_hz": config.center_frequency_hz,
                    "stop_frequency_hz": config.stop_frequency_hz,
                    "span_hz": config.span_hz,
                    "rbw_hz": config.rbw_hz,
                    "vbw_hz": (
                        config.vbw_hz
                        if ConfigRecordFlags(config.prefix.flags) & ConfigRecordFlags.VBW_VALID
                        else None
                    ),
                    "frame_width": config.frame_width,
                    "fft_size": config.fft_size,
                    "reference_level_dbm": config.reference_level_dbm,
                    "hardware_scale_db_per_code": config.hardware_scale_db_per_code,
                    "hardware_offset_dbm": config.hardware_offset_dbm,
                    "software_amplitude_offset_db": config.software_amplitude_offset_db,
                }
                for config in self.configurations
            ],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _enum_name(value: IntEnum | int) -> str | int:
    return value.name.lower() if isinstance(value, IntEnum) else value
