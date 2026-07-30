"""Pure native-packet adapter shared by SAN-90 integration tests and source."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

from .models import (
    RecordingConfiguration,
    RecordingPacket,
    TimingFlags,
    TraceRecordFlags,
)


def build_san90_recording_packet(
    *,
    configuration_generation: int,
    first_sequence: int,
    trace_count: int,
    frame_width: int,
    center_frequency_hz: float,
    start_frequency_hz: float,
    stop_frequency_hz: float,
    rbw_hz: float,
    vbw_hz: float | None,
    sweep_time_s: float | None,
    fft_size: int,
    reference_level_dbm: float,
    hardware_scale_db_per_code: float,
    hardware_offset_dbm: float,
    software_amplitude_offset_db: float,
    packet_acquisition_time_s: float,
    device_packet_timestamp_ns: int,
    sdk_trace_timestamp_step_raw: float,
    if_overflow: bool,
    if_overflow_latched: bool,
    configuration_metadata: Mapping[str, Any],
    host_receipt_unix_ns: int | None = None,
    host_receipt_monotonic_ns: int | None = None,
) -> RecordingPacket:
    if trace_count <= 0 or frame_width < 2:
        raise ValueError("native packet dimensions must be positive")
    timing = TimingFlags.NONE
    if device_packet_timestamp_ns:
        timing |= TimingFlags.DEVICE_TIMESTAMP_PRESENT
    packet_duration_ns = 0
    nominal_period_ns = 0
    if math.isfinite(packet_acquisition_time_s) and packet_acquisition_time_s > 0:
        packet_duration_ns = max(1, round(packet_acquisition_time_s * 1e9))
        nominal_period_ns = max(1, round(packet_duration_ns / trace_count))
        timing |= TimingFlags.PERIOD_FROM_PACKET_ACQUISITION
    trace_flags = TraceRecordFlags.NONE
    if if_overflow:
        trace_flags |= TraceRecordFlags.SDK_IF_OVERFLOW
    if if_overflow_latched:
        trace_flags |= TraceRecordFlags.IF_OVERFLOW_LATCHED
    span = stop_frequency_hz - start_frequency_hz
    configuration = RecordingConfiguration(
        configuration_generation=configuration_generation,
        center_frequency_hz=center_frequency_hz,
        start_frequency_hz=start_frequency_hz,
        stop_frequency_hz=stop_frequency_hz,
        span_hz=span,
        rbw_hz=rbw_hz,
        vbw_hz=vbw_hz,
        sweep_time_s=sweep_time_s,
        reference_level_dbm=reference_level_dbm,
        hardware_scale_db_per_code=hardware_scale_db_per_code,
        hardware_offset_dbm=hardware_offset_dbm,
        software_amplitude_offset_db=software_amplitude_offset_db,
        frame_width=frame_width,
        fft_size=fft_size,
        metadata=configuration_metadata,
    )
    return RecordingPacket(
        configuration=configuration,
        first_sequence=first_sequence,
        trace_count=trace_count,
        device_packet_timestamp_ns=device_packet_timestamp_ns,
        host_receipt_unix_ns=time.time_ns() if host_receipt_unix_ns is None else host_receipt_unix_ns,
        host_receipt_monotonic_ns=(
            time.monotonic_ns() if host_receipt_monotonic_ns is None else host_receipt_monotonic_ns
        ),
        nominal_trace_period_ns=nominal_period_ns,
        packet_acquisition_duration_ns=packet_duration_ns,
        sdk_trace_timestamp_step_raw=sdk_trace_timestamp_step_raw,
        timing_flags=timing,
        trace_flags=trace_flags,
    )
