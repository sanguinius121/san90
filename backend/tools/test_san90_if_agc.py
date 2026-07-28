"""Short, non-destructive SAN-90 RTA IF-AGC hardware diagnostic."""

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


CASES = (
    ("off", False, -9.0, 0.0),
    ("dynamic_-3", True, -3.0, 0.0),
    ("dynamic_-9", True, -9.0, 0.0),
    ("dynamic_-20", True, -20.0, 0.0),
    ("one_shot", True, -9.0, -1.0),
    ("periodic_1s", True, -9.0, 1.0),
    ("periodic_2s", True, -9.0, 2.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--reference-level-dbm", type=float, default=0.0)
    parser.add_argument("--sample-seconds", type=float, default=0.6)
    return parser.parse_args()


def base_settings(args: argparse.Namespace) -> AnalyzerSettings:
    return AnalyzerSettings(
        center_frequency_hz=args.center_hz,
        rbw_mode="auto",
        reference_level_dbm=args.reference_level_dbm,
        attenuation_db=None,
        preamplifier="off",
        gain_strategy="low-noise",
        if_agc_enabled=False,
        if_agc_target_dbfs=-9.0,
        if_agc_period_s=0.0,
        window="blackman-nuttall",
        detector="positive-peak",
    )


def main() -> int:
    args = parse_args()
    if not 0.1 <= args.sample_seconds <= 5:
        raise SystemExit("--sample-seconds must be between 0.1 and 5")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    source = San90Source()
    source.connect()
    conservative = base_settings(args)
    try:
        source.apply_settings(conservative)
        source.start()
        print(
            "case requested_enabled requested_target_dbfs requested_period_s "
            "actual_enabled actual_target_dbfs actual_period_s gains_db "
            "if_overflow stream_resumed"
        )
        for name, enabled, target, period in CASES:
            receipt_before = source.latest_receipt_monotonic_ns()
            source.apply_settings(
                replace(
                    conservative,
                    if_agc_enabled=enabled,
                    if_agc_target_dbfs=target,
                    if_agc_period_s=period,
                )
            )
            deadline = time.monotonic() + args.sample_seconds
            gains: list[str] = []
            resumed = False
            while time.monotonic() < deadline:
                state = source.get_settings_state()
                gain = state.actual.if_agc_gain_db
                gains.append("null" if gain is None else f"{gain:.6g}")
                receipt = source.latest_receipt_monotonic_ns()
                resumed = resumed or (
                    receipt is not None
                    and (receipt_before is None or receipt > receipt_before)
                )
                time.sleep(0.1)
            state = source.get_settings_state()
            status = source.get_status()
            print(
                f"{name} {enabled} {target:.6g} {period:.6g} "
                f"{state.actual.if_agc_enabled} "
                f"{state.actual.if_agc_target_dbfs:.6g} "
                f"{state.actual.if_agc_period_s:.6g} "
                f"{','.join(gains)} {status.if_overflow} {resumed}"
            )
        source.apply_settings(conservative)
    finally:
        source.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
