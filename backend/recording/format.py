"""Binary packing, unpacking, CRC, and validation for SAN-90 RTA files."""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import google_crc32c

from .models import (
    ConfigRecordFlags,
    ConfigurationRecord,
    EndFlags,
    EndRecord,
    EventCode,
    EventRecord,
    EventSeverity,
    FileFlags,
    FileHeader,
    GapFlags,
    GapReason,
    GapRecord,
    GenericRecord,
    ParsedRecord,
    RecordPrefix,
    RecordType,
    SessionMetadataRecord,
    StopReason,
    TimingFlags,
    TraceBatchRecord,
)


FILE_MAGIC = b"SAN90RTA"
RECORD_MAGIC = b"S9RR"
FORMAT_MAJOR = 1
FORMAT_MINOR = 0
BYTE_ORDER_MARKER = 0x01020304
MAX_RECORD_HEADER_LENGTH = 65_536
MAX_RECORD_LENGTH = 1 << 30

FILE_HEADER_STRUCT = struct.Struct("<8sHHIIIQ16sIIQQ20sI")
RECORD_PREFIX_STRUCT = struct.Struct("<4sHBBIQQIIIQ")
CONFIG_HEADER_STRUCT = struct.Struct("<QQQQQ7d4fII")
TRACE_HEADER_STRUCT = struct.Struct("<QQQIIQQQQQdII")
GAP_HEADER_STRUCT = struct.Struct("<QQQQQQQQQHHI")
EVENT_HEADER_STRUCT = struct.Struct("<QQHHIQQQ")
END_HEADER_STRUCT = struct.Struct("<QQHHIQQQQQQQQQQII")

FILE_HEADER_SIZE = 96
RECORD_PREFIX_SIZE = 48
CONFIG_RECORD_HEADER_SIZE = 168
TRACE_RECORD_HEADER_SIZE = 136
GAP_RECORD_HEADER_SIZE = 128
EVENT_RECORD_HEADER_SIZE = 96
END_RECORD_HEADER_SIZE = 160

assert FILE_HEADER_STRUCT.size == FILE_HEADER_SIZE
assert RECORD_PREFIX_STRUCT.size == RECORD_PREFIX_SIZE
assert RECORD_PREFIX_SIZE + CONFIG_HEADER_STRUCT.size == CONFIG_RECORD_HEADER_SIZE
assert RECORD_PREFIX_SIZE + TRACE_HEADER_STRUCT.size == TRACE_RECORD_HEADER_SIZE
assert RECORD_PREFIX_SIZE + GAP_HEADER_STRUCT.size == GAP_RECORD_HEADER_SIZE
assert RECORD_PREFIX_SIZE + EVENT_HEADER_STRUCT.size == EVENT_RECORD_HEADER_SIZE
assert RECORD_PREFIX_SIZE + END_HEADER_STRUCT.size == END_RECORD_HEADER_SIZE


class RecordingFormatError(ValueError):
    """A structural or checksum error at an exact file offset."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        offset: int | None = None,
        checksum_kind: str | None = None,
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.offset = offset
        self.checksum_kind = checksum_kind
        self.recoverable = recoverable


BytesLike = bytes | bytearray | memoryview


def _view(data: BytesLike) -> memoryview:
    view = memoryview(data)
    if view.ndim != 1 or view.format not in {"B", "b", "c"}:
        view = view.cast("B")
    if not view.c_contiguous:
        return memoryview(view.tobytes())
    return view


def _crc_input(data: BytesLike) -> bytes:
    # google-crc32c 1.8 requires an immutable bytes object. Conversion remains
    # a bulk C copy and never falls back to a Python per-byte checksum loop.
    return data if isinstance(data, bytes) else bytes(_view(data))


def crc32c(data: BytesLike) -> int:
    """Return a C-backed CRC32C as an unsigned uint32."""

    return int(google_crc32c.value(_crc_input(data))) & 0xFFFFFFFF


class Crc32c:
    """Incremental C-backed CRC32C used for the file rolling checksum."""

    def __init__(self) -> None:
        self._checksum = google_crc32c.Checksum()

    def update(self, data: BytesLike) -> None:
        self._checksum.update(_crc_input(data))

    @property
    def value(self) -> int:
        return int.from_bytes(self._checksum.digest(), "big", signed=False)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_json_object(payload: bytes, *, offset: int) -> Mapping[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise RecordingFormatError("json_bom", "JSON payload must not contain a UTF-8 BOM", offset=offset)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecordingFormatError("invalid_json", f"invalid UTF-8 JSON payload: {error}", offset=offset) from error
    if not isinstance(value, dict):
        raise RecordingFormatError("invalid_json", "JSON payload must contain an object", offset=offset)
    return value


def pack_file_header(
    *,
    creation_unix_ns: int,
    session_uuid: UUID | None = None,
    flags: FileFlags = FileFlags.NONE,
    format_major: int = FORMAT_MAJOR,
    format_minor: int = FORMAT_MINOR,
) -> bytes:
    values = (
        FILE_MAGIC,
        format_major,
        format_minor,
        BYTE_ORDER_MARKER,
        FILE_HEADER_SIZE,
        int(flags),
        creation_unix_ns,
        (session_uuid or uuid4()).bytes,
        RECORD_PREFIX_SIZE,
        MAX_RECORD_HEADER_LENGTH,
        FILE_HEADER_SIZE,
        MAX_RECORD_LENGTH,
        bytes(20),
        0,
    )
    try:
        header = bytearray(FILE_HEADER_STRUCT.pack(*values))
    except struct.error as error:
        raise ValueError(f"invalid file header value: {error}") from error
    struct.pack_into("<I", header, 92, crc32c(header))
    return bytes(header)


def unpack_file_header(data: BytesLike, *, offset: int = 0) -> FileHeader:
    view = _view(data)
    if len(view) < FILE_HEADER_SIZE:
        raise RecordingFormatError(
            "truncated_file_header",
            f"file header requires {FILE_HEADER_SIZE} bytes, found {len(view)}",
            offset=offset,
            recoverable=True,
        )
    values = FILE_HEADER_STRUCT.unpack_from(view)
    (
        magic,
        major,
        minor,
        byte_order,
        header_length,
        flags,
        creation_unix_ns,
        uuid_bytes,
        prefix_length,
        max_header_length,
        first_record_offset,
        max_record_length,
        reserved,
        stored_crc,
    ) = values
    if magic != FILE_MAGIC:
        raise RecordingFormatError("invalid_file_magic", f"invalid file magic {magic!r}", offset=offset)
    if major != FORMAT_MAJOR:
        raise RecordingFormatError(
            "unsupported_major_version",
            f"unsupported SAN-90 RTA format major version {major}",
            offset=offset,
        )
    if byte_order != BYTE_ORDER_MARKER:
        raise RecordingFormatError("invalid_byte_order", "invalid byte-order marker", offset=offset)
    if header_length != FILE_HEADER_SIZE or first_record_offset != FILE_HEADER_SIZE:
        raise RecordingFormatError(
            "invalid_file_header_length",
            f"version 1 file header and first record offset must be {FILE_HEADER_SIZE}",
            offset=offset,
        )
    if prefix_length != RECORD_PREFIX_SIZE:
        raise RecordingFormatError(
            "invalid_record_prefix_length",
            f"version 1 record prefix must be {RECORD_PREFIX_SIZE} bytes",
            offset=offset,
        )
    if max_header_length != MAX_RECORD_HEADER_LENGTH or max_record_length != MAX_RECORD_LENGTH:
        raise RecordingFormatError("invalid_file_limits", "version 1 file limits do not match the format", offset=offset)
    if reserved != bytes(20):
        raise RecordingFormatError("nonzero_reserved", "file header reserved bytes must be zero", offset=offset)
    crc_header = bytearray(view[:FILE_HEADER_SIZE])
    crc_header[92:96] = bytes(4)
    computed_crc = crc32c(crc_header)
    if computed_crc != stored_crc:
        raise RecordingFormatError(
            "file_header_crc",
            f"file header CRC32C mismatch: stored 0x{stored_crc:08x}, computed 0x{computed_crc:08x}",
            offset=offset,
            checksum_kind="file_header",
        )
    return FileHeader(
        format_major=major,
        format_minor=minor,
        byte_order_marker=byte_order,
        header_length=header_length,
        flags=FileFlags(flags),
        creation_unix_ns=creation_unix_ns,
        session_uuid=UUID(bytes=uuid_bytes),
        record_prefix_length=prefix_length,
        max_record_header_length=max_header_length,
        first_record_offset=first_record_offset,
        max_record_length=max_record_length,
        header_crc32c=stored_crc,
    )


def _validate_record_lengths(
    *,
    header_length: int,
    payload_length: int,
    total_record_length: int,
    offset: int,
) -> None:
    if header_length < RECORD_PREFIX_SIZE or header_length > MAX_RECORD_HEADER_LENGTH:
        raise RecordingFormatError(
            "invalid_record_header_length",
            f"record header length {header_length} is outside {RECORD_PREFIX_SIZE}..{MAX_RECORD_HEADER_LENGTH}",
            offset=offset,
        )
    if total_record_length != header_length + payload_length:
        raise RecordingFormatError(
            "invalid_total_record_length",
            f"record total {total_record_length} does not equal header {header_length} + payload {payload_length}",
            offset=offset,
        )
    if total_record_length > MAX_RECORD_LENGTH:
        raise RecordingFormatError(
            "record_too_large",
            f"record length {total_record_length} exceeds {MAX_RECORD_LENGTH}",
            offset=offset,
        )


def unpack_record_prefix(data: BytesLike, *, offset: int) -> RecordPrefix:
    view = _view(data)
    if len(view) < RECORD_PREFIX_SIZE:
        raise RecordingFormatError(
            "truncated_record_prefix",
            f"record prefix requires {RECORD_PREFIX_SIZE} bytes, found {len(view)}",
            offset=offset,
            recoverable=True,
        )
    (
        magic,
        record_type,
        record_version,
        flags,
        header_length,
        payload_length,
        record_index,
        header_crc,
        payload_crc,
        reserved,
        total_length,
    ) = RECORD_PREFIX_STRUCT.unpack_from(view)
    if magic != RECORD_MAGIC:
        raise RecordingFormatError("invalid_record_magic", f"invalid record magic {magic!r}", offset=offset)
    if reserved != 0:
        raise RecordingFormatError("nonzero_reserved", "record prefix reserved field must be zero", offset=offset)
    _validate_record_lengths(
        header_length=header_length,
        payload_length=payload_length,
        total_record_length=total_length,
        offset=offset,
    )
    return RecordPrefix(
        record_type=record_type,
        record_version=record_version,
        flags=flags,
        header_length=header_length,
        payload_length=payload_length,
        record_index=record_index,
        header_crc32c=header_crc,
        payload_crc32c=payload_crc,
        total_record_length=total_length,
    )


def verify_record_header(prefix: RecordPrefix, header: BytesLike, *, offset: int) -> None:
    view = _view(header)
    if len(view) != prefix.header_length:
        raise RecordingFormatError(
            "truncated_record_header",
            f"record header requires {prefix.header_length} bytes, found {len(view)}",
            offset=offset,
            recoverable=True,
        )
    crc_header = bytearray(view)
    crc_header[28:32] = bytes(4)
    computed_crc = crc32c(crc_header)
    if computed_crc != prefix.header_crc32c:
        raise RecordingFormatError(
            "record_header_crc",
            f"record header CRC32C mismatch: stored 0x{prefix.header_crc32c:08x}, computed 0x{computed_crc:08x}",
            offset=offset,
            checksum_kind="record_header",
        )


def verify_payload(prefix: RecordPrefix, payload: BytesLike, *, offset: int) -> None:
    view = _view(payload)
    if len(view) != prefix.payload_length:
        raise RecordingFormatError(
            "truncated_payload",
            f"record payload requires {prefix.payload_length} bytes, found {len(view)}",
            offset=offset,
            recoverable=True,
        )
    computed_crc = crc32c(view) if view else 0
    if computed_crc != prefix.payload_crc32c:
        raise RecordingFormatError(
            "payload_crc",
            f"payload CRC32C mismatch: stored 0x{prefix.payload_crc32c:08x}, computed 0x{computed_crc:08x}",
            offset=offset,
            checksum_kind="payload",
        )


def pack_record(
    *,
    record_type: RecordType | int,
    record_index: int,
    type_header: BytesLike = b"",
    payload: BytesLike = b"",
    flags: int = 0,
    record_version: int = 1,
) -> bytes:
    header_bytes = bytes(_view(type_header))
    payload_bytes = bytes(_view(payload))
    header = pack_record_header(
        record_type=record_type,
        record_index=record_index,
        type_header=header_bytes,
        payload_length=len(payload_bytes),
        payload_crc32c=crc32c(payload_bytes) if payload_bytes else 0,
        flags=flags,
        record_version=record_version,
    )
    return header + payload_bytes


def pack_record_header(
    *,
    record_type: RecordType | int,
    record_index: int,
    type_header: BytesLike = b"",
    payload_length: int = 0,
    payload_crc32c: int = 0,
    flags: int = 0,
    record_version: int = 1,
) -> bytes:
    """Pack only a record header, allowing a writer to stream payload separately."""

    header_bytes = bytes(_view(type_header))
    header_length = RECORD_PREFIX_SIZE + len(header_bytes)
    total_length = header_length + payload_length
    _validate_record_lengths(
        header_length=header_length,
        payload_length=payload_length,
        total_record_length=total_length,
        offset=0,
    )
    if not (0 <= int(record_type) <= 0xFFFF and 0 <= record_version <= 0xFF and 0 <= flags <= 0xFF):
        raise ValueError("record type, version, or flags are outside their integer widths")
    if record_index <= 0 or not 0 <= payload_crc32c <= 0xFFFFFFFF:
        raise ValueError("record index must be positive and payload CRC must fit uint32")
    if payload_length == 0 and payload_crc32c != 0:
        raise ValueError("empty payload CRC32C must be zero")
    prefix = RECORD_PREFIX_STRUCT.pack(
        RECORD_MAGIC,
        int(record_type),
        record_version,
        flags,
        header_length,
        payload_length,
        record_index,
        0,
        payload_crc32c,
        0,
        total_length,
    )
    header = bytearray(prefix + header_bytes)
    struct.pack_into("<I", header, 28, crc32c(header))
    return bytes(header)


def pack_session_metadata(*, record_index: int, metadata: Mapping[str, Any]) -> bytes:
    return pack_record(
        record_type=RecordType.SESSION_METADATA,
        record_index=record_index,
        payload=canonical_json_bytes(metadata),
    )


def validate_configuration(record: ConfigurationRecord) -> None:
    finite_values = (
        record.center_frequency_hz,
        record.start_frequency_hz,
        record.stop_frequency_hz,
        record.span_hz,
        record.rbw_hz,
        record.reference_level_dbm,
        record.hardware_scale_db_per_code,
        record.hardware_offset_dbm,
        record.software_amplitude_offset_db,
    )
    if not all(math.isfinite(value) for value in finite_values):
        raise RecordingFormatError("invalid_configuration", "configuration contains a non-finite value", offset=record.offset)
    if record.stop_frequency_hz <= record.start_frequency_hz:
        raise RecordingFormatError("invalid_configuration", "configuration stop frequency must exceed start", offset=record.offset)
    expected_span = record.stop_frequency_hz - record.start_frequency_hz
    if not math.isclose(record.span_hz, expected_span, rel_tol=1e-12, abs_tol=1e-3):
        raise RecordingFormatError("invalid_configuration", "configuration span does not match stop-start", offset=record.offset)
    if record.rbw_hz <= 0 or record.hardware_scale_db_per_code <= 0 or record.frame_width < 2:
        raise RecordingFormatError(
            "invalid_configuration",
            "configuration RBW/scale must be positive and frame width must be at least 2",
            offset=record.offset,
        )
    flags = ConfigRecordFlags(record.prefix.flags)
    if not flags & ConfigRecordFlags.OUTER_BIN_EDGES:
        raise RecordingFormatError(
            "invalid_configuration",
            "version 1 configuration must use the outer-bin-edge frequency model",
            offset=record.offset,
        )
    if flags & ConfigRecordFlags.VBW_VALID:
        if not math.isfinite(record.vbw_hz) or record.vbw_hz <= 0:
            raise RecordingFormatError("invalid_configuration", "flagged VBW must be finite and positive", offset=record.offset)
    elif record.vbw_hz != 0:
        raise RecordingFormatError("invalid_configuration", "unavailable VBW must be stored as zero", offset=record.offset)
    if flags & ConfigRecordFlags.SWEEP_TIME_VALID:
        if not math.isfinite(record.sweep_time_s) or record.sweep_time_s <= 0:
            raise RecordingFormatError(
                "invalid_configuration", "flagged sweep time must be finite and positive", offset=record.offset
            )
    elif record.sweep_time_s != 0:
        raise RecordingFormatError("invalid_configuration", "unavailable sweep time must be stored as zero", offset=record.offset)


def pack_configuration_record(
    *,
    record_index: int,
    config_id: int,
    configuration_generation: int,
    effective_first_sequence: int,
    effective_host_unix_ns: int,
    effective_host_monotonic_ns: int,
    center_frequency_hz: float,
    start_frequency_hz: float,
    stop_frequency_hz: float,
    span_hz: float,
    rbw_hz: float,
    vbw_hz: float,
    sweep_time_s: float,
    reference_level_dbm: float,
    hardware_scale_db_per_code: float,
    hardware_offset_dbm: float,
    software_amplitude_offset_db: float,
    frame_width: int,
    fft_size: int,
    metadata: Mapping[str, Any] | None = None,
    flags: ConfigRecordFlags = ConfigRecordFlags.OUTER_BIN_EDGES,
) -> bytes:
    type_header = CONFIG_HEADER_STRUCT.pack(
        config_id,
        configuration_generation,
        effective_first_sequence,
        effective_host_unix_ns,
        effective_host_monotonic_ns,
        center_frequency_hz,
        start_frequency_hz,
        stop_frequency_hz,
        span_hz,
        rbw_hz,
        vbw_hz,
        sweep_time_s,
        reference_level_dbm,
        hardware_scale_db_per_code,
        hardware_offset_dbm,
        software_amplitude_offset_db,
        frame_width,
        fft_size,
    )
    payload = canonical_json_bytes(metadata) if metadata is not None else b""
    packed = pack_record(
        record_type=RecordType.CONFIG,
        record_index=record_index,
        type_header=type_header,
        payload=payload,
        flags=int(flags),
    )
    prefix = unpack_record_prefix(packed[:RECORD_PREFIX_SIZE], offset=0)
    parsed = unpack_configuration_record(prefix, packed[:prefix.header_length], packed[prefix.header_length:], offset=0)
    validate_configuration(parsed)
    return packed


def pack_trace_batch_record(
    *,
    record_index: int,
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
    payload: BytesLike,
    flags: int = 0,
) -> bytes:
    payload_bytes = bytes(_view(payload))
    if trace_count <= 0 or frame_width <= 0 or len(payload_bytes) != trace_count * frame_width:
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
    return pack_record(
        record_type=RecordType.TRACE_BATCH,
        record_index=record_index,
        type_header=type_header,
        payload=payload_bytes,
        flags=flags,
    )


def pack_gap_record(
    *,
    record_index: int,
    config_id: int,
    configuration_generation: int,
    expected_sequence: int,
    next_sequence: int,
    estimated_lost_trace_count: int,
    start_monotonic_ns: int,
    end_monotonic_ns: int,
    start_device_timestamp_ns: int,
    end_device_timestamp_ns: int,
    reason_code: GapReason,
    gap_flags: GapFlags,
    detail_code: int = 0,
) -> bytes:
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
    return pack_record(record_type=RecordType.GAP, record_index=record_index, type_header=type_header)


def pack_event_record(
    *,
    record_index: int,
    event_unix_ns: int,
    event_monotonic_ns: int,
    event_code: EventCode,
    severity: EventSeverity,
    config_id: int = 0,
    configuration_generation: int = 0,
    sequence: int = 0,
    details: Mapping[str, Any] | None = None,
) -> bytes:
    type_header = EVENT_HEADER_STRUCT.pack(
        event_unix_ns,
        event_monotonic_ns,
        int(event_code),
        int(severity),
        0,
        config_id,
        configuration_generation,
        sequence,
    )
    payload = canonical_json_bytes(details) if details is not None else b""
    return pack_record(
        record_type=RecordType.EVENT,
        record_index=record_index,
        type_header=type_header,
        payload=payload,
    )


def pack_end_record(
    *,
    record_index: int,
    stop_unix_ns: int,
    stop_monotonic_ns: int,
    stop_reason: StopReason,
    end_flags: EndFlags,
    total_record_count: int,
    trace_batch_count: int,
    trace_count: int,
    raw_sample_count: int,
    bytes_before_end: int,
    final_file_bytes: int,
    gap_count: int,
    lost_trace_count: int,
    config_record_count: int,
    duration_ns: int,
    rolling_crc32c: int,
) -> bytes:
    type_header = END_HEADER_STRUCT.pack(
        stop_unix_ns,
        stop_monotonic_ns,
        int(stop_reason),
        int(end_flags),
        0,
        total_record_count,
        trace_batch_count,
        trace_count,
        raw_sample_count,
        bytes_before_end,
        final_file_bytes,
        gap_count,
        lost_trace_count,
        config_record_count,
        duration_ns,
        rolling_crc32c,
        0,
    )
    return pack_record(record_type=RecordType.END, record_index=record_index, type_header=type_header)


def _require_layout(prefix: RecordPrefix, *, expected_header: int, payload_allowed: bool, offset: int) -> None:
    if prefix.header_length != expected_header:
        raise RecordingFormatError(
            "invalid_type_header_length",
            f"record type {prefix.record_type} requires header length {expected_header}, found {prefix.header_length}",
            offset=offset,
        )
    if not payload_allowed and prefix.payload_length:
        raise RecordingFormatError(
            "unexpected_payload",
            f"record type {prefix.record_type} does not allow a payload",
            offset=offset,
        )


def validate_type_header_before_payload(prefix: RecordPrefix, header: bytes, *, offset: int) -> None:
    """Validate known version-1 layout and trace dimensions before payload allocation."""

    if prefix.record_version != 1:
        return
    try:
        record_type = RecordType(prefix.record_type)
    except ValueError:
        return
    layouts = {
        RecordType.SESSION_METADATA: (RECORD_PREFIX_SIZE, True),
        RecordType.CONFIG: (CONFIG_RECORD_HEADER_SIZE, True),
        RecordType.TRACE_BATCH: (TRACE_RECORD_HEADER_SIZE, True),
        RecordType.GAP: (GAP_RECORD_HEADER_SIZE, False),
        RecordType.EVENT: (EVENT_RECORD_HEADER_SIZE, True),
        RecordType.END: (END_RECORD_HEADER_SIZE, False),
    }
    expected_header, payload_allowed = layouts[record_type]
    _require_layout(prefix, expected_header=expected_header, payload_allowed=payload_allowed, offset=offset)
    if record_type == RecordType.TRACE_BATCH:
        values = TRACE_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE)
        trace_count, frame_width = values[3], values[4]
        if trace_count == 0 or frame_width == 0:
            raise RecordingFormatError(
                "invalid_trace_dimensions", "trace count and frame width must be nonzero", offset=offset
            )
        if trace_count * frame_width != prefix.payload_length:
            raise RecordingFormatError(
                "invalid_trace_payload_length",
                f"trace payload {prefix.payload_length} does not equal {trace_count} * {frame_width}",
                offset=offset,
            )


def unpack_session_metadata_record(
    prefix: RecordPrefix, header: bytes, payload: bytes, *, offset: int
) -> SessionMetadataRecord:
    _require_layout(prefix, expected_header=RECORD_PREFIX_SIZE, payload_allowed=True, offset=offset)
    metadata = decode_json_object(payload, offset=offset) if payload else {}
    return SessionMetadataRecord(offset, prefix, metadata, payload)


def unpack_configuration_record(
    prefix: RecordPrefix, header: bytes, payload: bytes, *, offset: int
) -> ConfigurationRecord:
    _require_layout(prefix, expected_header=CONFIG_RECORD_HEADER_SIZE, payload_allowed=True, offset=offset)
    values = CONFIG_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE)
    metadata = decode_json_object(payload, offset=offset) if payload else {}
    record = ConfigurationRecord(offset, prefix, *values, metadata, payload)
    validate_configuration(record)
    return record


def unpack_trace_batch_record(
    prefix: RecordPrefix, header: bytes, payload: bytes, *, offset: int
) -> TraceBatchRecord:
    _require_layout(prefix, expected_header=TRACE_RECORD_HEADER_SIZE, payload_allowed=True, offset=offset)
    values = TRACE_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE)
    reserved = values[-1]
    if reserved != 0:
        raise RecordingFormatError("nonzero_reserved", "trace header reserved field must be zero", offset=offset)
    (
        config_id,
        generation,
        first_sequence,
        trace_count,
        frame_width,
        device_timestamp,
        host_unix,
        host_monotonic,
        nominal_period,
        packet_duration,
        sdk_step,
        timing_flags,
        _,
    ) = values
    if trace_count == 0 or frame_width == 0:
        raise RecordingFormatError("invalid_trace_dimensions", "trace count and frame width must be nonzero", offset=offset)
    expected_payload = trace_count * frame_width
    if expected_payload != prefix.payload_length:
        raise RecordingFormatError(
            "invalid_trace_payload_length",
            f"trace payload {prefix.payload_length} does not equal {trace_count} * {frame_width}",
            offset=offset,
        )
    return TraceBatchRecord(
        offset,
        prefix,
        config_id,
        generation,
        first_sequence,
        trace_count,
        frame_width,
        device_timestamp,
        host_unix,
        host_monotonic,
        nominal_period,
        packet_duration,
        sdk_step,
        TimingFlags(timing_flags),
        payload,
    )


def _enum_or_int(enum_type: type[Any], value: int) -> Any:
    try:
        return enum_type(value)
    except ValueError:
        return value


def unpack_gap_record(prefix: RecordPrefix, header: bytes, payload: bytes, *, offset: int) -> GapRecord:
    _require_layout(prefix, expected_header=GAP_RECORD_HEADER_SIZE, payload_allowed=False, offset=offset)
    values = list(GAP_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE))
    values[9] = _enum_or_int(GapReason, values[9])
    values[10] = GapFlags(values[10])
    return GapRecord(offset, prefix, *values)


def unpack_event_record(prefix: RecordPrefix, header: bytes, payload: bytes, *, offset: int) -> EventRecord:
    _require_layout(prefix, expected_header=EVENT_RECORD_HEADER_SIZE, payload_allowed=True, offset=offset)
    event_unix, event_mono, event_code, severity, reserved, config_id, generation, sequence = (
        EVENT_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE)
    )
    if reserved != 0:
        raise RecordingFormatError("nonzero_reserved", "event header reserved field must be zero", offset=offset)
    details = decode_json_object(payload, offset=offset) if payload else {}
    return EventRecord(
        offset,
        prefix,
        event_unix,
        event_mono,
        _enum_or_int(EventCode, event_code),
        _enum_or_int(EventSeverity, severity),
        config_id,
        generation,
        sequence,
        details,
        payload,
    )


def unpack_end_record(
    prefix: RecordPrefix,
    header: bytes,
    payload: bytes,
    *,
    offset: int,
    computed_rolling_crc32c: int | None = None,
) -> EndRecord:
    _require_layout(prefix, expected_header=END_RECORD_HEADER_SIZE, payload_allowed=False, offset=offset)
    values = list(END_HEADER_STRUCT.unpack_from(header, RECORD_PREFIX_SIZE))
    if values[4] != 0 or values[-1] != 0:
        raise RecordingFormatError("nonzero_reserved", "END reserved fields must be zero", offset=offset)
    values[2] = _enum_or_int(StopReason, values[2])
    values[3] = EndFlags(values[3])
    del values[-1]
    del values[4]
    return EndRecord(offset, prefix, *values, computed_rolling_crc32c=computed_rolling_crc32c)


def unpack_known_record(
    prefix: RecordPrefix,
    header: bytes,
    payload: bytes,
    *,
    offset: int,
    computed_rolling_crc32c: int | None = None,
) -> ParsedRecord:
    if prefix.record_version != 1:
        return GenericRecord(offset, prefix)
    try:
        record_type = RecordType(prefix.record_type)
    except ValueError:
        return GenericRecord(offset, prefix)
    if record_type == RecordType.SESSION_METADATA:
        return unpack_session_metadata_record(prefix, header, payload, offset=offset)
    if record_type == RecordType.CONFIG:
        return unpack_configuration_record(prefix, header, payload, offset=offset)
    if record_type == RecordType.TRACE_BATCH:
        return unpack_trace_batch_record(prefix, header, payload, offset=offset)
    if record_type == RecordType.GAP:
        return unpack_gap_record(prefix, header, payload, offset=offset)
    if record_type == RecordType.EVENT:
        return unpack_event_record(prefix, header, payload, offset=offset)
    if record_type == RecordType.END:
        return unpack_end_record(
            prefix,
            header,
            payload,
            offset=offset,
            computed_rolling_crc32c=computed_rolling_crc32c,
        )
    return GenericRecord(offset, prefix)
