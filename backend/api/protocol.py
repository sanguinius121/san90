"""Versioned little-endian binary display protocol."""

from __future__ import annotations

import json
import math
import struct
import time
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import numpy as np

from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.models import SpectrumTemporalFrame, WaterfallBatch

MAGIC = b"SAN9"
PROTOCOL_VERSION = 2
WATERFALL_BATCH_VERSION = 3
SPECTRUM_TEMPORAL_VERSION = 4

MESSAGE_SPECTRUM = 0x01
MESSAGE_SPECTRUM_TEMPORAL = 0x02
MESSAGE_WATERFALL = 0x03
MESSAGE_STATUS = 0x10
MESSAGE_AI_DETECTIONS = 0x11
MESSAGE_ERROR = 0x12

SOURCE_SIMULATOR = 0x01
SOURCE_SAN90 = 0x02

PAYLOAD_FLOAT32 = 0x01
PAYLOAD_UINT8 = 0x02
PAYLOAD_JSON_UTF8 = 0x03
PAYLOAD_FLOAT32_PAIR = 0x04

# magic, version, message, source, payload type, header bytes, flags,
# sequence, device timestamp, host timestamp, configuration generation, point count, payload bytes,
# start, center, stop, span, RBW, reference level.
HEADER = struct.Struct("<4sBBBBHHQQQQII5df")
HEADER_SIZE = HEADER.size

# Version 3 is used only by waterfall batches in Subphase A. Version-2
# spectrum/status and legacy one-row waterfall messages remain unchanged.
# magic/version/message/source/payload/header/flags, batch sequence, first row
# sequence, first device/host timestamps, generation, nominal row period,
# row count, point count, payload bytes, reserved, frequency/RBW, reference.
WATERFALL_BATCH_HEADER = struct.Struct("<4sBBBBHHQQQQQQIIII5df")
WATERFALL_BATCH_HEADER_SIZE = WATERFALL_BATCH_HEADER.size

# Version 4 combined spectrum: newest trace followed by interval maximum.
# Both payload arrays are point_count little-endian float32 values.
SPECTRUM_TEMPORAL_HEADER = struct.Struct("<4sBBBBHHQQQQQQIIII5dfff")
SPECTRUM_TEMPORAL_HEADER_SIZE = SPECTRUM_TEMPORAL_HEADER.size


def _source_code(source: str) -> int:
    if source == "san90":
        return SOURCE_SAN90
    if source == "simulator":
        return SOURCE_SIMULATOR
    raise ValueError(f"unsupported source type {source!r}")


def _validate_metadata(metadata: RawTraceMetadata, point_count: int) -> None:
    if point_count < 0:
        raise ValueError("point_count must not be negative")
    numeric = (
        metadata.start_frequency_hz,
        metadata.center_frequency_hz,
        metadata.stop_frequency_hz,
        metadata.span_hz,
        metadata.rbw_hz,
        metadata.reference_level_dbm,
    )
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError("binary frame metadata must be finite")
    if metadata.stop_frequency_hz <= metadata.start_frequency_hz or metadata.span_hz <= 0:
        raise ValueError("binary frame frequency metadata is invalid")
    if not math.isclose(
        metadata.stop_frequency_hz - metadata.start_frequency_hz,
        metadata.span_hz,
        rel_tol=1e-9,
        abs_tol=1e-3,
    ):
        raise ValueError("binary frame start/stop/span metadata is inconsistent")


def _pack_header(
    message_type: int,
    source: str,
    payload_type: int,
    metadata: RawTraceMetadata,
    point_count: int,
    payload_length: int,
) -> bytes:
    _validate_metadata(metadata, point_count)
    return HEADER.pack(
        MAGIC,
        PROTOCOL_VERSION,
        message_type,
        _source_code(source),
        payload_type,
        HEADER_SIZE,
        0,
        metadata.sequence,
        metadata.device_timestamp_ns,
        metadata.host_timestamp_ns,
        metadata.configuration_generation,
        point_count,
        payload_length,
        metadata.start_frequency_hz,
        metadata.center_frequency_hz,
        metadata.stop_frequency_hz,
        metadata.span_hz,
        metadata.rbw_hz,
        metadata.reference_level_dbm,
    )


def pack_spectrum(source: str, metadata: RawTraceMetadata, values: np.ndarray) -> bytes:
    if values.size == 0 or values.dtype != np.float32 or values.ndim != 1 or not values.flags.c_contiguous:
        raise ValueError("spectrum payload must be contiguous one-dimensional float32")
    if not np.isfinite(values).all():
        raise ValueError("spectrum payload contains non-finite values")
    payload = values.astype("<f4", copy=False).tobytes(order="C")
    return _pack_header(MESSAGE_SPECTRUM, source, PAYLOAD_FLOAT32, metadata, values.size, len(payload)) + payload


def pack_spectrum_temporal(source: str, frame: SpectrumTemporalFrame) -> bytes:
    expected_payload = frame.point_count * np.dtype("<f4").itemsize * 2
    latest = frame.latest_trace_float32.astype("<f4", copy=False).tobytes(order="C")
    maximum = frame.interval_max_trace_float32.astype("<f4", copy=False).tobytes(order="C")
    payload = latest + maximum
    if len(payload) != expected_payload:
        raise ValueError("temporal spectrum payload length is inconsistent")
    numeric = (
        frame.start_frequency_hz, frame.center_frequency_hz, frame.stop_frequency_hz,
        frame.span_hz, frame.rbw_hz, frame.reference_level_dbm,
        frame.scale_to_dbm, frame.offset_to_dbm,
    )
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError("temporal spectrum metadata must be finite")
    if frame.stop_frequency_hz <= frame.start_frequency_hz or not math.isclose(
        frame.stop_frequency_hz - frame.start_frequency_hz, frame.span_hz,
        rel_tol=1e-9, abs_tol=1e-3,
    ):
        raise ValueError("temporal spectrum frequency metadata is inconsistent")
    return SPECTRUM_TEMPORAL_HEADER.pack(
        MAGIC, SPECTRUM_TEMPORAL_VERSION, MESSAGE_SPECTRUM_TEMPORAL,
        _source_code(source), PAYLOAD_FLOAT32_PAIR,
        SPECTRUM_TEMPORAL_HEADER_SIZE, 0,
        frame.sequence, frame.device_timestamp_ns or 0, frame.host_timestamp_ns,
        frame.generation, frame.interval_start_monotonic_ns, frame.interval_end_monotonic_ns,
        frame.traces_integrated, frame.point_count, len(payload), 0,
        frame.start_frequency_hz, frame.center_frequency_hz, frame.stop_frequency_hz,
        frame.span_hz, frame.rbw_hz, frame.reference_level_dbm,
        frame.scale_to_dbm, frame.offset_to_dbm,
    ) + payload


def pack_waterfall(source: str, metadata: RawTraceMetadata, values: np.ndarray) -> bytes:
    if values.size == 0 or values.dtype != np.uint8 or values.ndim != 1 or not values.flags.c_contiguous:
        raise ValueError("waterfall payload must be contiguous one-dimensional uint8")
    payload = values.tobytes(order="C")
    return _pack_header(MESSAGE_WATERFALL, source, PAYLOAD_UINT8, metadata, values.size, len(payload)) + payload


def pack_waterfall_batch(source: str, batch: WaterfallBatch) -> bytes:
    payload = batch.values.tobytes(order="C")
    expected = batch.row_count * batch.point_count
    if len(payload) != expected:
        raise ValueError("waterfall batch payload length does not match row_count × point_count")
    numeric = (
        batch.start_frequency_hz,
        batch.center_frequency_hz,
        batch.stop_frequency_hz,
        batch.span_hz,
        batch.rbw_hz,
        batch.reference_level_dbm,
    )
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError("waterfall batch metadata must be finite")
    if batch.stop_frequency_hz <= batch.start_frequency_hz or batch.span_hz <= 0:
        raise ValueError("waterfall batch frequency metadata is invalid")
    if not math.isclose(batch.stop_frequency_hz - batch.start_frequency_hz, batch.span_hz, rel_tol=1e-9, abs_tol=1e-3):
        raise ValueError("waterfall batch start/stop/span metadata is inconsistent")
    return WATERFALL_BATCH_HEADER.pack(
        MAGIC,
        WATERFALL_BATCH_VERSION,
        MESSAGE_WATERFALL,
        _source_code(source),
        PAYLOAD_UINT8,
        WATERFALL_BATCH_HEADER_SIZE,
        0,
        batch.batch_sequence,
        batch.first_row_sequence,
        batch.first_device_timestamp_ns,
        batch.first_host_timestamp_ns,
        batch.configuration_generation,
        batch.nominal_row_period_ns,
        batch.row_count,
        batch.point_count,
        len(payload),
        0,
        batch.start_frequency_hz,
        batch.center_frequency_hz,
        batch.stop_frequency_hz,
        batch.span_hz,
        batch.rbw_hz,
        batch.reference_level_dbm,
    ) + payload


def _pack_json_message(message_type: int, source: str, sequence: int, data: Any) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    metadata = RawTraceMetadata(
        sequence=sequence,
        device_timestamp_ns=0,
        host_timestamp_ns=time.time_ns(),
        receipt_monotonic_ns=time.monotonic_ns(),
        start_frequency_hz=0.0,
        center_frequency_hz=0.0,
        stop_frequency_hz=1.0,
        span_hz=1.0,
        rbw_hz=0.0,
        reference_level_dbm=0.0,
        mapping=RawAmplitudeMapping(1.0, 0.0),
        configuration_generation=int(data.get("configuration_generation", 0)) if isinstance(data, dict) else 0,
    )
    return _pack_header(message_type, source, PAYLOAD_JSON_UTF8, metadata, 0, len(payload)) + payload


def pack_status(source: str, sequence: int, status: Any) -> bytes:
    data = asdict(status) if is_dataclass(status) else status
    return _pack_json_message(MESSAGE_STATUS, source, sequence, data)


def pack_ai_detections(source: str, sequence: int, result: Mapping[str, Any]) -> bytes:
    return _pack_json_message(MESSAGE_AI_DETECTIONS, source, sequence, dict(result))


def unpack_header(message: bytes) -> dict[str, int | float | bytes]:
    if len(message) < 12:
        raise ValueError("message is shorter than the protocol header")
    version = message[4]
    if version == SPECTRUM_TEMPORAL_VERSION:
        if len(message) < SPECTRUM_TEMPORAL_HEADER_SIZE:
            raise ValueError("message is shorter than the temporal spectrum header")
        fields = SPECTRUM_TEMPORAL_HEADER.unpack_from(message)
        result = dict(zip(
            (
                "magic", "version", "message_type", "source_type", "payload_type", "header_size", "flags",
                "sequence", "device_timestamp_ns", "host_timestamp_ns", "configuration_generation",
                "interval_start_monotonic_ns", "interval_end_monotonic_ns", "traces_integrated",
                "point_count", "payload_length", "reserved", "start_frequency_hz", "center_frequency_hz",
                "stop_frequency_hz", "span_hz", "rbw_hz", "reference_level_dbm", "scale_to_dbm", "offset_to_dbm",
            ),
            fields,
        ))
        points = int(result["point_count"])
        expected = points * 8
        if result["magic"] != MAGIC or result["message_type"] != MESSAGE_SPECTRUM_TEMPORAL:
            raise ValueError("invalid temporal spectrum protocol identity")
        if result["header_size"] != SPECTRUM_TEMPORAL_HEADER_SIZE:
            raise ValueError("invalid temporal spectrum header size")
        if points < 2 or int(result["traces_integrated"]) < 1:
            raise ValueError("invalid temporal spectrum dimensions")
        if int(result["interval_end_monotonic_ns"]) < int(result["interval_start_monotonic_ns"]):
            raise ValueError("invalid temporal spectrum interval")
        if result["payload_type"] != PAYLOAD_FLOAT32_PAIR or int(result["payload_length"]) != expected:
            raise ValueError("invalid temporal spectrum payload dimensions")
        if len(message) != SPECTRUM_TEMPORAL_HEADER_SIZE + expected:
            raise ValueError("binary protocol payload length mismatch")
        if not all(math.isfinite(float(result[key])) for key in (
            "start_frequency_hz", "center_frequency_hz", "stop_frequency_hz", "span_hz", "rbw_hz",
            "reference_level_dbm", "scale_to_dbm", "offset_to_dbm",
        )):
            raise ValueError("temporal spectrum metadata must be finite")
        if not np.isfinite(np.frombuffer(message, dtype="<f4", count=points * 2, offset=SPECTRUM_TEMPORAL_HEADER_SIZE)).all():
            raise ValueError("temporal spectrum payload contains non-finite values")
        return result
    if version == WATERFALL_BATCH_VERSION:
        if len(message) < WATERFALL_BATCH_HEADER_SIZE:
            raise ValueError("message is shorter than the waterfall batch header")
        fields = WATERFALL_BATCH_HEADER.unpack_from(message)
        result = dict(zip(
            (
                "magic", "version", "message_type", "source_type", "payload_type", "header_size", "flags",
                "sequence", "first_row_sequence", "device_timestamp_ns", "host_timestamp_ns",
                "configuration_generation", "nominal_row_period_ns", "row_count", "point_count",
                "payload_length", "reserved", "start_frequency_hz", "center_frequency_hz",
                "stop_frequency_hz", "span_hz", "rbw_hz", "reference_level_dbm",
            ),
            fields,
        ))
        if result["magic"] != MAGIC or result["message_type"] != MESSAGE_WATERFALL:
            raise ValueError("invalid waterfall batch protocol identity")
        if result["header_size"] != WATERFALL_BATCH_HEADER_SIZE:
            raise ValueError("invalid waterfall batch header size")
        if int(result["row_count"]) <= 0 or int(result["point_count"]) <= 0:
            raise ValueError("waterfall batch dimensions must be positive")
        if int(result["nominal_row_period_ns"]) <= 0:
            raise ValueError("waterfall batch row period must be positive")
        expected = int(result["row_count"]) * int(result["point_count"])
        if result["payload_type"] != PAYLOAD_UINT8 or int(result["payload_length"]) != expected:
            raise ValueError("invalid waterfall batch payload dimensions")
        if len(message) != WATERFALL_BATCH_HEADER_SIZE + expected:
            raise ValueError("binary protocol payload length mismatch")
        return result
    if len(message) < HEADER_SIZE:
        raise ValueError("message is shorter than the protocol header")
    fields = HEADER.unpack_from(message)
    result = dict(zip(
        (
            "magic", "version", "message_type", "source_type", "payload_type", "header_size", "flags",
            "sequence", "device_timestamp_ns", "host_timestamp_ns", "configuration_generation", "point_count", "payload_length",
            "start_frequency_hz", "center_frequency_hz", "stop_frequency_hz", "span_hz", "rbw_hz",
            "reference_level_dbm",
        ),
        fields,
    ))
    if result["magic"] != MAGIC or result["version"] != PROTOCOL_VERSION or result["header_size"] != HEADER_SIZE:
        raise ValueError("invalid binary protocol identity")
    if len(message) != HEADER_SIZE + int(result["payload_length"]):
        raise ValueError("binary protocol payload length mismatch")
    return result
