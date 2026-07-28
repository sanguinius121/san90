"""Canonical HTRA VBW mode mapping and validation."""

from __future__ import annotations

import math

from .errors import AnalyzerConfigurationError


# VBWMode_TypeDef in htra_api.h.
VBW_MODE_VALUES = {
    "manual": 0x00,
    "ratio-1": 0x01,
    "ratio-0.1": 0x02,
    "ratio-0.01": 0x03,
    "ratio-10": 0x04,
}

VBW_MODE_RATIOS = {
    "ratio-1": 1.0,
    "ratio-0.1": 0.1,
    "ratio-0.01": 0.01,
    "ratio-10": 10.0,
}

# Manual and 0.01× materially reduce acquisition responsiveness on SAN-90.
# The 10× mode is intentionally hidden as well; the application defaults to
# 0.1× and exposes only the two filtered ratio choices.
VBW_EXPOSED_MODES = ("ratio-1", "ratio-0.1")

VBW_MANUAL_REQUEST_MIN_HZ = 1.0
VBW_MANUAL_REQUEST_MAX_HZ = 200_000_000.0
VBW_MANUAL_UI_STEP_HZ = 1.0


def validate_vbw_mode(mode: str) -> str:
    if mode not in VBW_MODE_VALUES:
        raise AnalyzerConfigurationError(
            f"Unsupported vbw_mode {mode!r}; expected one of {tuple(VBW_MODE_VALUES)}"
        )
    return mode


def validate_manual_vbw(value: float | None) -> float:
    if value is None:
        raise AnalyzerConfigurationError("manual VBW mode requires vbw_hz")
    result = float(value)
    if (
        not math.isfinite(result)
        or result < VBW_MANUAL_REQUEST_MIN_HZ
        or result > VBW_MANUAL_REQUEST_MAX_HZ
    ):
        raise AnalyzerConfigurationError(
            f"vbw_hz must be between {VBW_MANUAL_REQUEST_MIN_HZ} and "
            f"{VBW_MANUAL_REQUEST_MAX_HZ} Hz"
        )
    return result


def verified_vbw_hz(value: float) -> float | None:
    result = float(value)
    return result if math.isfinite(result) and result > 0 else None
