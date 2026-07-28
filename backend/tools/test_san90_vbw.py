"""Short, non-destructive SAN-90 RTA VBW hardware diagnostic."""

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
from backend.analyzer.vbw import VBW_MODE_VALUES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--sample-seconds", type=float, default=0.3)
    parser.add_argument(
        "--manual-values-hz",
        type=float,
        nargs="+",
        default=[1, 100, 603.060913, 12_345.67, 60_306.091, 603_060.913, 10_000_000, 100_000_000],
    )
    return parser.parse_args()


def base_settings(args: argparse.Namespace) -> AnalyzerSettings:
    return AnalyzerSettings(
        center_frequency_hz=args.center_hz,
        rbw_mode="auto",
        rbw_hz=None,
        vbw_mode="ratio-0.1",
        vbw_hz=6_030.609,
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


def run_case(
    source: San90Source,
    name: str,
    requested: AnalyzerSettings,
    sample_seconds: float,
) -> None:
    before = source.get_status()
    started = time.monotonic()
    try:
        source.apply_settings(requested)
    except Exception as error:
        print(f"{name} ERROR {type(error).__name__}: {error}")
        return
    configured = time.monotonic()
    time.sleep(sample_seconds)
    after = source.get_status()
    state = source.get_settings_state()
    elapsed = max(time.monotonic() - configured, 1e-9)
    trace_rate = (after.sdk_frames_received - before.sdk_frames_received) / elapsed
    print(
        f"{name} requested_rbw_mode={requested.rbw_mode} "
        f"requested_rbw_hz={requested.rbw_hz} actual_rbw_hz={state.actual.rbw_hz:.9g} "
        f"requested_vbw_mode={requested.vbw_mode} requested_vbw_hz={requested.vbw_hz} "
        f"actual_vbw_mode={state.actual.vbw_mode} actual_vbw_hz={state.actual.vbw_hz} "
        f"points={state.actual.point_count} trace_rate_hz={trace_rate:.1f} "
        f"configure_ms={(configured-started)*1000:.3f} errors={after.acquisition_errors} "
        f"timeouts={source._diagnostics.timeouts} if_overflow={after.if_overflow}"
    )


def main() -> int:
    args = parse_args()
    if not 0.1 <= args.sample_seconds <= 3:
        raise SystemExit("--sample-seconds must be between 0.1 and 3")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    source = San90Source()
    conservative = base_settings(args)
    source.connect()
    try:
        source.apply_settings(conservative)
        source.start()
        for mode in VBW_MODE_VALUES:
            request = replace(conservative, vbw_mode=mode)
            if mode == "manual":
                request = replace(request, vbw_hz=60_306.091)
            run_case(source, f"auto_rbw_{mode}", request, args.sample_seconds)
        for value in args.manual_values_hz:
            run_case(
                source,
                f"manual_vbw_{value:g}",
                replace(conservative, vbw_mode="manual", vbw_hz=value),
                args.sample_seconds,
            )
        for rbw_request in (50_000.0, 300_000.0):
            for mode in ("ratio-0.01", "ratio-1", "ratio-10", "manual"):
                request = replace(
                    conservative,
                    rbw_mode="manual",
                    rbw_hz=rbw_request,
                    vbw_mode=mode,
                    vbw_hz=12_345.67 if mode == "manual" else conservative.vbw_hz,
                )
                run_case(source, f"rbw_{rbw_request:g}_{mode}", request, args.sample_seconds)
        source.apply_settings(conservative)
    finally:
        source.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
