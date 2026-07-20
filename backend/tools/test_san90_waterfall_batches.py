#!/usr/bin/env python3
"""Opt-in SAN-90 safe/fast waterfall validation without FastAPI."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analyzer.models import AnalyzerSettings  # noqa: E402
from backend.analyzer.san90 import San90Source  # noqa: E402
from backend.api.protocol import pack_spectrum, pack_waterfall_batch  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--center-hz", type=float, default=2.45e9)
    parser.add_argument("--safe-duration", type=float, default=5.0)
    parser.add_argument("--fast-duration", type=float, default=30.0)
    parser.add_argument("--stability-duration", type=float, default=600.0)
    parser.add_argument("--report-interval", type=float, default=10.0)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if args.device_index < 0:
        parser.error("--device-index must be non-negative")
    if args.center_hz <= 0 or min(args.safe_duration, args.fast_duration, args.report_interval) <= 0:
        parser.error("frequencies and non-stability durations must be positive")
    if args.stability_duration < 0:
        parser.error("--stability-duration must not be negative")
    return args


def safe_settings(center_hz: float) -> AnalyzerSettings:
    return AnalyzerSettings(
        mode="rta",
        center_frequency_hz=center_hz,
        reference_level_dbm=0.0,
        attenuation_db=None,
        preamplifier="off",
        gain_strategy="low-noise",
        rbw_mode="auto",
        rbw_hz=None,
        window="blackman-nuttall",
        detector="positive-peak",
    )


def measure(source: San90Source, name: str, duration_s: float, report_interval_s: float) -> dict[str, object]:
    state = source.get_settings_state()
    before_status = source.get_status()
    before_metrics = source.get_waterfall_metrics()
    if before_metrics is None:
        raise RuntimeError("waterfall producer is unavailable")
    started = time.monotonic()
    cpu_started = time.process_time()
    deadline = started + duration_s
    next_report = started + min(duration_s, report_interval_s)
    spectrum_frames = 0
    batches = 0
    rows = 0
    waterfall_wire_bytes = 0
    spectrum_wire_bytes = 0
    malformed_batches = 0
    generations: set[int] = set()
    batch_row_counts: set[int] = set()
    while time.monotonic() < deadline:
        frame = source.read_frame()
        if frame is not None:
            spectrum_frames += 1
            generations.add(frame.configuration_generation)
            metadata = source._raw_accumulator.metadata if source._raw_accumulator is not None else None
            if metadata is not None:
                spectrum_wire_bytes += len(pack_spectrum("san90", metadata, frame.values))
        batch = source.read_waterfall_batch()
        if batch is not None:
            batches += 1
            rows += batch.row_count
            generations.add(batch.configuration_generation)
            batch_row_counts.add(batch.row_count)
            if batch.point_count != state.actual.point_count or batch.values.shape != (batch.row_count, batch.point_count):
                malformed_batches += 1
            waterfall_wire_bytes += len(pack_waterfall_batch("san90", batch))
        now = time.monotonic()
        if now >= next_report:
            status = source.get_status()
            metrics = source.get_waterfall_metrics()
            assert metrics is not None
            elapsed = now - started
            print(
                f"{name}: {elapsed:.1f}s sdk={status.sdk_frames_received-before_status.sdk_frames_received} "
                f"rows={metrics.completed_rows-before_metrics.completed_rows} "
                f"batches={metrics.completed_batches-before_metrics.completed_batches}",
                flush=True,
            )
            next_report += report_interval_s
        time.sleep(0.001)
    elapsed = time.monotonic() - started
    cpu_s = time.process_time() - cpu_started
    after_status = source.get_status()
    after_metrics = source.get_waterfall_metrics()
    diagnostics = source.get_diagnostics()
    assert after_metrics is not None
    sdk_traces = after_status.sdk_frames_received - before_status.sdk_frames_received
    completed_rows = after_metrics.completed_rows - before_metrics.completed_rows
    completed_batches = after_metrics.completed_batches - before_metrics.completed_batches
    return {
        "name": name,
        "duration_s": elapsed,
        "configuration_generation": state.configuration_generation,
        "actual": asdict(state.actual),
        "sdk_traces_per_second": sdk_traces / elapsed,
        "point_rate_mps": sdk_traces * state.actual.point_count / elapsed / 1e6,
        "spectrum_frames_per_second": spectrum_frames / elapsed,
        "waterfall_rows_per_second": completed_rows / elapsed,
        "waterfall_batches_per_second": completed_batches / elapsed,
        "consumed_rows_per_second": rows / elapsed,
        "consumed_batches_per_second": batches / elapsed,
        "normal_batch_row_counts": sorted(batch_row_counts),
        "waterfall_wire_bytes_per_second": waterfall_wire_bytes / elapsed,
        "spectrum_wire_bytes_per_second": spectrum_wire_bytes / elapsed,
        "estimated_total_wire_bytes_per_second": (waterfall_wire_bytes + spectrum_wire_bytes) / elapsed,
        "process_cpu_percent_one_core": 100.0 * cpu_s / elapsed,
        "rss_max_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0,
        "timeouts": diagnostics.timeouts,
        "invalid_packets": diagnostics.invalid_packets,
        "acquisition_errors": after_status.acquisition_errors,
        "malformed_batches": malformed_batches,
        "observed_generations": sorted(generations),
        "producer": asdict(after_metrics),
    }


def validate_profile(result: dict[str, object], *, fast: bool) -> None:
    actual = result["actual"]
    assert isinstance(actual, dict)
    expected_points = 832 if fast else 3328
    expected_rbw = 241_224.365234375 if fast else 60_306.09130859375
    expected_rows = 240.0 if fast else 60.0
    expected_batch_rows = 4 if fast else 1
    minimum_sdk_rate = 27_000.0 if fast else 6_800.0
    if actual["point_count"] != expected_points:
        raise RuntimeError(f"expected {expected_points} points, received {actual['point_count']}")
    if abs(float(actual["rbw_hz"]) - expected_rbw) > 2.0:
        raise RuntimeError(f"unexpected actual RBW {actual['rbw_hz']}")
    if float(result["sdk_traces_per_second"]) < minimum_sdk_rate:
        raise RuntimeError(f"SDK rate regression: {result['sdk_traces_per_second']:.1f} traces/s")
    if float(result["waterfall_rows_per_second"]) < expected_rows * 0.93:
        raise RuntimeError(f"waterfall row-rate regression: {result['waterfall_rows_per_second']:.1f} rows/s")
    if result["normal_batch_row_counts"] != [expected_batch_rows]:
        raise RuntimeError(f"unexpected batch row counts: {result['normal_batch_row_counts']}")
    if int(result["malformed_batches"]) or int(result["acquisition_errors"]):
        raise RuntimeError("malformed batches or acquisition errors were observed")


def main() -> int:
    args = parse_args()
    source = San90Source(device_index=args.device_index)
    safe = safe_settings(args.center_hz)
    results: dict[str, object] = {}
    try:
        source.connect()
        source.apply_settings(safe)
        source.start()
        results["safe"] = measure(source, "safe", args.safe_duration, args.report_interval)
        validate_profile(results["safe"], fast=False)  # type: ignore[arg-type]

        fast = source.get_settings_state().requested.updated(rbw_mode="manual", rbw_hz=300_000.0)
        source.apply_settings(fast)
        results["fast_30s"] = measure(source, "fast", args.fast_duration, args.report_interval)
        validate_profile(results["fast_30s"], fast=True)  # type: ignore[arg-type]
        if args.stability_duration:
            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
            stability = measure(source, "stability", args.stability_duration, args.report_interval)
            validate_profile(stability, fast=True)
            stability["rss_growth_mib"] = float(stability["rss_max_mib"]) - rss_before
            results["stability"] = stability

        source.apply_settings(safe)
        results["restored_safe"] = measure(source, "restored", max(1.0, args.safe_duration), args.report_interval)
        validate_profile(results["restored_safe"], fast=False)  # type: ignore[arg-type]
    finally:
        try:
            if source.get_device_info() is not None:
                source.apply_settings(safe)
        finally:
            source.stop()
            source.disconnect()

    reopened = San90Source(device_index=args.device_index)
    try:
        reopened.connect()
        reopened.apply_settings(safe)
        reopened.start()
        results["immediate_reopen"] = measure(reopened, "reopen", 1.0, 1.0)
        validate_profile(results["immediate_reopen"], fast=False)  # type: ignore[arg-type]
    finally:
        try:
            if reopened.get_device_info() is not None:
                reopened.apply_settings(safe)
        finally:
            reopened.stop()
            reopened.disconnect()

    output = json.dumps(results, indent=2, sort_keys=True)
    print(output)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
