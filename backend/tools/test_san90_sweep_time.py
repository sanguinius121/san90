"""Short, non-destructive SAN-90 RTA sweep-time hardware diagnostic."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.sweep_time import SWEEP_TIME_MODE_VALUES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--sample-seconds", type=float, default=0.5)
    return parser.parse_args()


def base_settings(args: argparse.Namespace) -> AnalyzerSettings:
    return AnalyzerSettings(
        center_frequency_hz=args.center_hz,
        rbw_mode="auto",
        rbw_hz=None,
        vbw_mode="ratio-0.1",
        vbw_hz=6_030.609,
        sweep_time_mode="minimum",
        sweep_time_multiple=3.0,
        sweep_time_s=0.001,
        reference_level_dbm=0.0,
        attenuation_db=None,
        preamplifier="off",
        gain_strategy="low-noise",
        if_agc_enabled=False,
        if_agc_target_dbfs=-9.0,
        if_agc_period_s=0.0,
        window="blackman-nuttall",
        detector="positive-peak",
    )


def run_case(source: San90Source, name: str, requested: AnalyzerSettings, seconds: float) -> None:
    before = source.get_status()
    started = time.monotonic()
    try:
        source.apply_settings(requested)
    except Exception as error:
        print(f"{name} ERROR {type(error).__name__}: {error}")
        return
    configured = time.monotonic()
    time.sleep(seconds)
    state = source.get_settings_state()
    after = source.get_status()
    elapsed = max(time.monotonic() - configured, 1e-9)
    trace_rate = (after.sdk_frames_received - before.sdk_frames_received) / elapsed
    waterfall = source.get_waterfall_metrics()
    print(
        f"{name} requested_mode={requested.sweep_time_mode} "
        f"enum={SWEEP_TIME_MODE_VALUES[requested.sweep_time_mode]} "
        f"requested_multiple={requested.sweep_time_multiple} "
        f"requested_manual_s={requested.sweep_time_s} "
        f"actual_mode={state.actual.sweep_time_mode} "
        f"returned_multiple={state.actual.sweep_time_multiple} "
        f"actual_trace_period_s={state.actual.sweep_time_s} "
        f"rbw_hz={state.actual.rbw_hz:.9g} points={state.actual.point_count} "
        f"fft={state.actual.fft_size} trace_rate_hz={trace_rate:.1f} "
        f"waterfall_rows_s={0 if waterfall is None else waterfall.actual_rows_per_second:.1f} "
        f"configure_ms={(configured-started)*1000:.3f} timeouts={source._diagnostics.timeouts} "
        f"errors={after.acquisition_errors} if_overflow={after.if_overflow}"
    )


def main() -> int:
    args = parse_args()
    if not 0.2 <= args.sample_seconds <= 3:
        raise SystemExit("--sample-seconds must be between 0.2 and 3")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    source = San90Source()
    conservative = base_settings(args)
    source.connect()
    try:
        source.apply_settings(conservative)
        source.start()
        for mode in (
            "minimum",
            "minimum-x2",
            "minimum-x4",
            "minimum-x10",
            "minimum-x20",
            "minimum-x50",
        ):
            run_case(source, mode, replace(conservative, sweep_time_mode=mode), args.sample_seconds)
        source.apply_settings(conservative)
        minimum_sweep_s = source.get_settings_state().actual.sweep_time_s or 32.768e-6
        for multiple in (0.5, 3.0, 8.0, 100.0):
            run_case(
                source,
                f"custom_{multiple:g}",
                replace(conservative, sweep_time_mode="custom-multiple", sweep_time_multiple=multiple),
                args.sample_seconds,
            )
        for target in (max(minimum_sweep_s / 2, 1e-6), minimum_sweep_s * 2, 0.01):
            run_case(
                source,
                f"manual_{target:g}",
                replace(conservative, sweep_time_mode="manual", sweep_time_s=target),
                args.sample_seconds,
            )
        for mode in ("minimum", "minimum-x4", "manual"):
            request = replace(
                conservative,
                rbw_mode="manual",
                rbw_hz=300_000.0,
                sweep_time_mode=mode,
                sweep_time_s=0.001,
            )
            run_case(source, f"rbw_300k_{mode}", request, args.sample_seconds)
        source.apply_settings(conservative)
    finally:
        source.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
