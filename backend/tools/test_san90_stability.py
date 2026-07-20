#!/usr/bin/env python3
"""Sustained SAN-90 temporal/waterfall validation with safe restoration."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.tradeoff import SAN90_RESOLUTION_TRADEOFF_STEPS


def rss_mib() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024.0
    raise RuntimeError("VmRSS is unavailable")


def safe_settings() -> AnalyzerSettings:
    return AnalyzerSettings(
        mode="rta", center_frequency_hz=2.45e9, rbw_mode="auto", rbw_hz=None,
        reference_level_dbm=0.0, attenuation_db=None, preamplifier="off",
        gain_strategy="low-noise", window="blackman-nuttall", detector="positive-peak",
    )


def apply_step(source: San90Source, index: int) -> int:
    step = SAN90_RESOLUTION_TRADEOFF_STEPS[index]
    requested = source.get_settings_state().requested.updated(rbw_mode="manual", rbw_hz=step.requested_rbw_hz)
    source.apply_settings(requested)
    state = source.get_settings_state()
    if state.actual.resolution_tradeoff_index != index:
        raise AssertionError(f"requested step {index}, got {state.actual.resolution_tradeoff_index}")
    return state.configuration_generation


def hold(source: San90Source, index: int, duration_s: float) -> dict[str, object]:
    generation = apply_step(source, index)
    start_status = source.get_status()
    start_rss = rss_mib()
    minimum_rss = maximum_rss = start_rss
    temporal_frames = temporal_traces = waterfall_batches = waterfall_rows = 0
    stale_temporal = stale_waterfall = 0
    started = time.monotonic()
    next_report = started + 60.0
    deadline = started + duration_s
    while time.monotonic() < deadline:
        temporal = source.read_spectrum_temporal()
        if temporal is not None:
            if temporal.generation != generation:
                stale_temporal += 1
            else:
                temporal_frames += 1
                temporal_traces += temporal.traces_integrated
        batch = source.read_waterfall_batch()
        if batch is not None:
            if batch.configuration_generation != generation:
                stale_waterfall += 1
            else:
                waterfall_batches += 1
                waterfall_rows += batch.row_count
        current_rss = rss_mib()
        minimum_rss = min(minimum_rss, current_rss)
        maximum_rss = max(maximum_rss, current_rss)
        now = time.monotonic()
        if now >= next_report:
            print(json.dumps({"progress_s": round(now - started, 1), "rss_mib": current_rss,
                              "temporal_frames": temporal_frames, "waterfall_rows": waterfall_rows}), flush=True)
            next_report += 60.0
        time.sleep(0.0005)
    elapsed = time.monotonic() - started
    end_status = source.get_status()
    temporal_metrics = source.get_spectrum_temporal_metrics()
    waterfall_metrics = source.get_waterfall_metrics()
    result: dict[str, object] = {
        "step_index": index,
        "duration_s": elapsed,
        "generation": generation,
        "sdk_traces_per_second": (end_status.sdk_frames_received - start_status.sdk_frames_received) / elapsed,
        "temporal_frames_per_second": temporal_frames / elapsed,
        "mean_traces_per_temporal_frame": temporal_traces / temporal_frames if temporal_frames else 0.0,
        "waterfall_batches_per_second": waterfall_batches / elapsed,
        "waterfall_rows_per_second": waterfall_rows / elapsed,
        "stale_temporal_frames": stale_temporal,
        "stale_waterfall_batches": stale_waterfall,
        "rss_start_mib": start_rss,
        "rss_end_mib": rss_mib(),
        "rss_minimum_mib": minimum_rss,
        "rss_maximum_mib": maximum_rss,
        "temporal_metrics": temporal_metrics,
        "waterfall_metrics": None if waterfall_metrics is None else asdict(waterfall_metrics),
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def run(duration_s: float, step_index: int, transition_cycles: int) -> None:
    source = San90Source()
    safe = safe_settings()
    try:
        source.connect()
        source.apply_settings(safe)
        source.start()
        hold(source, step_index, duration_s)
        transition_order = (7, 0, 4)
        transitions: list[dict[str, int]] = []
        for _ in range(transition_cycles):
            for index in transition_order:
                generation = apply_step(source, index)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    frame = source.read_spectrum_temporal()
                    if frame is not None and frame.generation == generation:
                        transitions.append({"index": index, "generation": generation, "point_count": frame.point_count})
                        break
                    time.sleep(0.001)
                else:
                    raise AssertionError(f"no current-generation temporal frame after transition to {index}")
        print(json.dumps({"transitions": transitions}), flush=True)
        source.apply_settings(safe)
        restored = source.get_settings_state()
        if restored.actual.rbw_mode != "auto" or restored.actual.point_count != 3328:
            raise AssertionError("safe Auto RBW restoration failed")
        print(json.dumps({"restored": asdict(restored)}, sort_keys=True), flush=True)
    finally:
        source.stop()
        source.disconnect()

    reopened = San90Source()
    try:
        reopened.connect()
        reopened.apply_settings(safe)
        reopened.start()
        time.sleep(0.1)
        state = reopened.get_settings_state()
        if state.actual.rbw_mode != "auto":
            raise AssertionError("immediate reopen did not restore Auto RBW")
        print(json.dumps({"immediate_reopen": asdict(state)}, sort_keys=True), flush=True)
    finally:
        reopened.stop()
        reopened.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--step-index", type=int, default=0, choices=range(len(SAN90_RESOLUTION_TRADEOFF_STEPS)))
    parser.add_argument("--transition-cycles", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.duration <= 0 or arguments.transition_cycles < 0:
        parser.error("duration must be positive and transition cycles non-negative")
    run(arguments.duration, arguments.step_index, arguments.transition_cycles)
