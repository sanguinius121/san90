"""Validated SAN-90 IF AGC semantics shared by sources and API controls."""

from __future__ import annotations

import math

from .errors import AnalyzerConfigurationError

IF_AGC_TARGET_MIN_DBFS = -30.0
IF_AGC_TARGET_MAX_DBFS = 0.0
IF_AGC_TARGET_UI_STEP_DB = 1.0
IF_AGC_PERIOD_MIN_S = -1.0
IF_AGC_PERIOD_MAX_S = 2_147_483.0
IF_AGC_PERIOD_UI_STEP_S = 1.0
IF_AGC_ONE_SHOT_PERIOD_S = -1.0
IF_AGC_DYNAMIC_PERIOD_S = 0.0


def validate_if_agc_target(value: float) -> float:
    target = float(value)
    if not math.isfinite(target) or not IF_AGC_TARGET_MIN_DBFS <= target <= IF_AGC_TARGET_MAX_DBFS:
        raise AnalyzerConfigurationError(
            f"if_agc_target_dbfs must be between {IF_AGC_TARGET_MIN_DBFS} and "
            f"{IF_AGC_TARGET_MAX_DBFS} dBFS"
        )
    return target


def validate_if_agc_period(value: float) -> float:
    period = float(value)
    if not math.isfinite(period) or not IF_AGC_PERIOD_MIN_S <= period <= IF_AGC_PERIOD_MAX_S:
        raise AnalyzerConfigurationError(
            f"if_agc_period_s must be between {IF_AGC_PERIOD_MIN_S} and "
            f"{IF_AGC_PERIOD_MAX_S} seconds"
        )
    return period
