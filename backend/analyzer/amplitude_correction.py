"""Application-level amplitude correction; the HTRA SDK has no offset control."""

from __future__ import annotations

import math

from .raw_buffers import RawAmplitudeMapping

AMPLITUDE_OFFSET_MIN_DB = -100.0
AMPLITUDE_OFFSET_MAX_DB = 100.0
AMPLITUDE_OFFSET_STEP_DB = 1.0


def validate_amplitude_offset(value_db: float) -> float:
    value = float(value_db)
    if not math.isfinite(value):
        raise ValueError("amplitude offset must be finite")
    if not AMPLITUDE_OFFSET_MIN_DB <= value <= AMPLITUDE_OFFSET_MAX_DB:
        raise ValueError(
            f"amplitude offset must be between {AMPLITUDE_OFFSET_MIN_DB:g} and "
            f"{AMPLITUDE_OFFSET_MAX_DB:g} dB"
        )
    return value


def corrected_amplitude_mapping(
    hardware_mapping: RawAmplitudeMapping,
    amplitude_offset_db: float,
) -> RawAmplitudeMapping:
    """Return one calibrated mapping implementing corrected = measured + offset."""
    correction = validate_amplitude_offset(amplitude_offset_db)
    return RawAmplitudeMapping(
        scale_db_per_code=hardware_mapping.scale_db_per_code,
        offset_dbm=hardware_mapping.offset_dbm + correction,
    )
