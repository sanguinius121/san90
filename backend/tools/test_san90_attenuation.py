"""Short hardware diagnostic for SAN-90 RTA attenuation configuration."""

from __future__ import annotations

import argparse
import logging

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--values", type=int, nargs="+", default=[0, 5, 10, 20])
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--reference-level-dbm", type=float, default=0.0)
    return parser.parse_args()


def settings(args: argparse.Namespace, attenuation_db: int | None) -> AnalyzerSettings:
    return AnalyzerSettings(
        mode="rta",
        center_frequency_hz=args.center_hz,
        span_hz=None,
        rbw_hz=None,
        rbw_mode="auto",
        vbw_hz=None,
        reference_level_dbm=args.reference_level_dbm,
        attenuation_db=attenuation_db,
        preamplifier="off",
        gain_strategy="low-noise",
        if_agc_enabled=False,
        window="blackman-nuttall",
        detector="positive-peak",
    )


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    source = San90Source()
    source.connect()
    try:
        source.apply_settings(settings(args, None))
        source.start()
        print("requested_mode requested_atten_db readback_atten_db preamplifier gain_strategy if_agc")
        for requested in args.values:
            source.apply_settings(settings(args, requested))
            state = source.get_settings_state()
            print(
                f"manual {requested} {state.actual.attenuation_db} "
                f"{state.actual.preamplifier} {state.actual.gain_strategy} "
                f"{state.requested.if_agc_enabled}"
            )
        source.apply_settings(settings(args, None))
        restored = source.get_settings_state()
        print(
            f"auto -1 {restored.actual.attenuation_db} "
            f"{restored.actual.preamplifier} {restored.actual.gain_strategy} "
            f"{restored.requested.if_agc_enabled}"
        )
    finally:
        source.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
