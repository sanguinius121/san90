"""Verified application names for HTRA RTA control enum values."""

from .htra import FORCED_OFF, HIGH_LINEARITY_PREFERRED, LOW_NOISE_PREFERRED

PREAMPLIFIER_VALUES: dict[str, int] = {
    "auto": 0,
    "off": FORCED_OFF,
    "low": 2,
    "medium": 3,
    "high": 4,
}

GAIN_STRATEGY_VALUES: dict[str, int] = {
    "low-noise": LOW_NOISE_PREFERRED,
    "high-linearity": HIGH_LINEARITY_PREFERRED,
}

SAN90_MANUAL_ATTENUATION_STEP_DB = 3
SAN90_MANUAL_ATTENUATION_MIN_DB = 3
SAN90_MANUAL_ATTENUATION_MAX_DB = 33

RBW_MODE_VALUES: dict[str, int] = {
    "manual": 0x00,
    "auto": 0x01,
}

# Gaussian_CISPR (0x0a) is deliberately excluded: the SDK header marks it
# as supported only in EMC mode, while this application uses continuous RTA.
WINDOW_VALUES: dict[str, int] = {
    "flat-top": 0x00,
    "blackman-nuttall": 0x01,
    "low-sidelobe": 0x02,
    "rectangular": 0x03,
    "kaiser": 0x04,
}

# RTA_Profile_TypeDef.Detector uses Detector_TypeDef. MaxPower and RawFrames
# are excluded because the SDK header marks both as SWP-only.
DETECTOR_VALUES: dict[str, int] = {
    "sample": 0x00,
    "positive-peak": 0x01,
    "average": 0x02,
    "negative-peak": 0x03,
    "rms": 0x06,
    "auto-peak": 0x07,
}


def enum_name(values: dict[str, int], native_value: int) -> str | None:
    return next((name for name, value in values.items() if value == native_value), None)


def attenuation_readback(
    actual_attenuation_db: int | None,
    requested_attenuation_db: int | None,
) -> tuple[int | None, bool]:
    """Separate the SDK's actual attenuation from its requested auto/manual mode."""
    actual = None if actual_attenuation_db in {None, -1} else actual_attenuation_db
    return actual, requested_attenuation_db is None


def normalize_manual_attenuation(requested_db: int) -> int:
    """Map a manual request to the 3 dB grid verified on SAN-90 hardware."""
    bounded = max(SAN90_MANUAL_ATTENUATION_MIN_DB, min(SAN90_MANUAL_ATTENUATION_MAX_DB, requested_db))
    return (bounded // SAN90_MANUAL_ATTENUATION_STEP_DB) * SAN90_MANUAL_ATTENUATION_STEP_DB
