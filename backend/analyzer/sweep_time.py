"""Canonical HTRA RTA sweep-time mode mapping and validation."""

from __future__ import annotations

import math

from .errors import AnalyzerConfigurationError


SWEEP_TIME_MODE_VALUES = {
    "minimum": 0x00,
    "minimum-x2": 0x01,
    "minimum-x4": 0x02,
    "minimum-x10": 0x03,
    "minimum-x20": 0x04,
    "minimum-x50": 0x05,
    "custom-multiple": 0x06,
    "manual": 0x07,
}

SWEEP_TIME_FIXED_MULTIPLES = {
    "minimum": 1.0,
    "minimum-x2": 2.0,
    "minimum-x4": 4.0,
    "minimum-x10": 10.0,
    "minimum-x20": 20.0,
    "minimum-x50": 50.0,
}

# Conservative application bounds verified on the connected SAN-90. The SDK
# field is a double, but values below 1x cannot make the device faster than its
# current minimum sweep time.
SWEEP_TIME_MULTIPLE_MIN = 1.0
SWEEP_TIME_MULTIPLE_MAX = 100.0
SWEEP_TIME_MULTIPLE_STEP = 1.0
MANUAL_SWEEP_TIME_MIN_S = 1e-6
MANUAL_SWEEP_TIME_MAX_S = 10e-3
MANUAL_SWEEP_TIME_STEP_S = 1e-6


def validate_sweep_time_mode(mode: str) -> str:
    if mode not in SWEEP_TIME_MODE_VALUES:
        raise AnalyzerConfigurationError(
            f"Unsupported sweep_time_mode {mode!r}; expected one of {tuple(SWEEP_TIME_MODE_VALUES)}"
        )
    return mode


def validate_sweep_time_multiple(value: float | None) -> float:
    if value is None:
        raise AnalyzerConfigurationError("custom sweep-time mode requires sweep_time_multiple")
    result = float(value)
    if (
        not math.isfinite(result)
        or result < SWEEP_TIME_MULTIPLE_MIN
        or result > SWEEP_TIME_MULTIPLE_MAX
    ):
        raise AnalyzerConfigurationError(
            f"sweep_time_multiple must be between {SWEEP_TIME_MULTIPLE_MIN:g} and "
            f"{SWEEP_TIME_MULTIPLE_MAX:g}"
        )
    return result


def validate_manual_sweep_time(value: float | None) -> float:
    if value is None:
        raise AnalyzerConfigurationError("manual sweep-time mode requires sweep_time_s")
    result = float(value)
    if (
        not math.isfinite(result)
        or result < MANUAL_SWEEP_TIME_MIN_S
        or result > MANUAL_SWEEP_TIME_MAX_S
    ):
        raise AnalyzerConfigurationError(
            f"sweep_time_s must be between {MANUAL_SWEEP_TIME_MIN_S:g} and "
            f"{MANUAL_SWEEP_TIME_MAX_S:g} seconds"
        )
    return result


def actual_trace_period_s(packet_acquisition_s: float, packet_frames: int) -> float | None:
    if not math.isfinite(packet_acquisition_s) or packet_acquisition_s <= 0 or packet_frames <= 0:
        return None
    return packet_acquisition_s / packet_frames
