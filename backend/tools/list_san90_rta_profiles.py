#!/usr/bin/env python3
"""Measure documented SAN-90 RTA RBW/window/detector configurations.

The SDK has no finite RTA profile enum. This utility therefore tests only the
numeric RBW requests supplied on the command line (or values used by official
SDK spectrum examples), plus explicitly documented RTA enum members.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analyzer.control_mapping import DETECTOR_VALUES, WINDOW_VALUES
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--reference-level-dbm", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=1.0, help="Seconds used to measure each configuration")
    parser.add_argument("--rbw-hz", type=float, action="append", help="Manual RBW request; may be repeated")
    parser.add_argument("--include-windows", action="store_true")
    parser.add_argument("--include-detectors", action="store_true")
    parser.add_argument(
        "--distinct-summary", action="store_true",
        help="Emit a final time-to-frequency ordered list with coerced duplicate profiles removed.",
    )
    return parser.parse_args()


def _rate_policy(trace_rate_hz: float) -> tuple[float, float, int, float, float]:
    target_rows = trace_rate_hz / 127.0
    rows_per_batch = min(8, max(1, round(target_rows / 60.0)))
    waterfall_rows = 60.0 * rows_per_batch
    spectrum_fps = min(240.0, max(60.0, 60.0 * 2 ** round(math.log2(max(1.0, trace_rate_hz / 7_635.0)))))
    webgl_fps = min(120.0, spectrum_fps)
    return waterfall_rows, 60.0, rows_per_batch, spectrum_fps, webgl_fps


def distinct_manual_profiles(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Deduplicate hardware coercions and sort from time to frequency priority."""
    distinct: dict[tuple[float, int, int], dict[str, object]] = {}
    for row in rows:
        if not row.get("success") or row.get("requested_rbw_mode") != "manual":
            continue
        key = (round(float(row["actual_rbw_hz"]), 3), int(row["point_count"]), int(row["fft_size"]))
        distinct.setdefault(key, row)
    return sorted(distinct.values(), key=lambda item: (-float(item["actual_rbw_hz"]), int(item["point_count"])))


def measure(source: San90Source, identifier: str, requested: AnalyzerSettings, duration: float) -> dict[str, object]:
    before_frames = source.get_status().sdk_frames_received
    before_cpu = time.process_time()
    started = time.perf_counter()
    source.apply_settings(requested)
    first_valid_s = time.perf_counter() - started
    time.sleep(duration)
    elapsed = time.perf_counter() - started
    cpu_s = time.process_time() - before_cpu
    state = source.get_settings_state()
    frame_info = source._frame_info
    mapping = source.latest_raw_amplitude_mapping()
    profile = source._profile_out
    frames = source.get_status().sdk_frames_received - before_frames
    assert frame_info is not None and profile is not None and mapping is not None
    trace_rate = frames / max(duration, 1e-9)
    waterfall_rows, waterfall_batches, rows_per_batch, spectrum_fps, webgl_fps = _rate_policy(trace_rate)
    span_hz = state.actual.span_hz
    return {
        "identifier": identifier,
        "requested_rbw_hz": requested.rbw_hz,
        "requested_rbw_mode": requested.rbw_mode,
        "actual_rbw_hz": state.actual.rbw_hz,
        "actual_rbw_mode": state.actual.rbw_mode,
        "window": state.actual.window,
        "window_sdk_value": int(profile.Window),
        "detector": state.actual.detector,
        "detector_sdk_value": int(profile.Detector),
        "point_count": state.actual.point_count,
        "fft_size": int(frame_info.FFTSize),
        "start_frequency_hz": state.actual.start_frequency_hz,
        "stop_frequency_hz": state.actual.stop_frequency_hz,
        "span_hz": span_hz,
        "sdk_trace_fps": trace_rate,
        "frequency_bin_spacing_hz": span_hz / state.actual.point_count,
        "waterfall_rows_per_second": waterfall_rows,
        "waterfall_batches_per_second": waterfall_batches,
        "waterfall_rows_per_batch": rows_per_batch,
        "nominal_time_per_row_s": 1.0 / waterfall_rows,
        "target_traces_per_row": trace_rate / waterfall_rows,
        "spectrum_publish_fps": spectrum_fps,
        "webgl_target_fps": webgl_fps,
        "effective_point_rate": frames * state.actual.point_count / max(duration, 1e-9),
        "process_cpu_percent": 100.0 * cpu_s / max(elapsed, 1e-9),
        "scale_to_dbm": mapping.scale_db_per_code,
        "offset_to_dbm": mapping.offset_dbm,
        "configuration_generation": state.configuration_generation,
        "first_valid_frame_latency_ms": first_valid_s * 1000.0,
        "success": True,
    }


def main() -> int:
    args = parse_args()
    if args.duration <= 0 or args.center_hz <= 0:
        raise SystemExit("--duration and --center-hz must be positive")
    rbw_values = args.rbw_hz or [15e3, 50e3, 300e3]
    if any(value <= 0 for value in rbw_values):
        raise SystemExit("all --rbw-hz values must be positive")
    safe = AnalyzerSettings(
        mode="rta",
        center_frequency_hz=args.center_hz,
        reference_level_dbm=args.reference_level_dbm,
        attenuation_db=None,
        preamplifier="off",
        gain_strategy="low-noise",
        rbw_mode="auto",
        rbw_hz=None,
    )
    source = San90Source(device_index=args.device_index)
    rows: list[dict[str, object]] = []
    try:
        source.connect()
        source.apply_settings(safe)
        source.start()
        candidates: list[tuple[str, AnalyzerSettings]] = [("rbw:auto", safe)]
        candidates.extend((f"rbw:manual:{value:g}", safe.updated(rbw_mode="manual", rbw_hz=value)) for value in rbw_values)
        if args.include_windows:
            candidates.extend((f"window:{name}", safe.updated(window=name)) for name in WINDOW_VALUES)
        if args.include_detectors:
            candidates.extend((f"detector:{name}", safe.updated(detector=name)) for name in DETECTOR_VALUES)
        for identifier, settings in candidates:
            try:
                row = measure(source, identifier, settings, args.duration)
            except Exception as error:
                row = {"identifier": identifier, "success": False, "error": str(error)}
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
        if args.distinct_summary:
            print(json.dumps({"distinct_manual_profiles": distinct_manual_profiles(rows)}, sort_keys=True), flush=True)
    finally:
        try:
            if source.get_device_info() is not None:
                source.apply_settings(safe)
                print(json.dumps({"restored": asdict(source.get_settings_state())}, sort_keys=True), flush=True)
        finally:
            source.stop()
            source.disconnect()
    return 0 if all(row.get("success") for row in rows) else 1


if __name__ == "__main__":
    os.environ.setdefault("SAN90_SPECTRUM_FPS", "60")
    os.environ.setdefault("SAN90_WATERFALL_FPS", "60")
    raise SystemExit(main())
