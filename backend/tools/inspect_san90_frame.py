#!/usr/bin/env python3
"""Inspect a saved SAN-90 diagnostic frame without plotting it."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


REQUIRED_FIELDS = {
    "trace_dbm",
    "start_frequency_hz",
    "stop_frequency_hz",
    "center_frequency_hz",
    "span_hz",
    "rbw_hz",
    "reference_level_dbm",
    "timestamp_ns",
    "sequence",
}


@dataclass(frozen=True, slots=True)
class FrameSummary:
    shape: tuple[int, ...]
    dtype: str
    finite_count: int
    minimum_dbm: float
    maximum_dbm: float
    mean_dbm: float
    frequency_resolution_hz: float
    strongest_bin_index: int
    strongest_bin_frequency_hz: float
    strongest_bin_amplitude_dbm: float


def inspect_frame(path: Path) -> FrameSummary:
    with np.load(path, allow_pickle=False) as saved:
        missing = REQUIRED_FIELDS.difference(saved.files)
        if missing:
            raise ValueError(f"Missing required NPZ fields: {', '.join(sorted(missing))}")
        trace = np.asarray(saved["trace_dbm"])
        if trace.ndim != 1 or trace.size == 0:
            raise ValueError(f"trace_dbm must be a non-empty one-dimensional array, got {trace.shape}")
        if trace.dtype != np.float32:
            raise ValueError(f"trace_dbm must have dtype float32, got {trace.dtype}")
        finite = np.isfinite(trace)
        finite_count = int(np.count_nonzero(finite))
        if finite_count != trace.size:
            raise ValueError(f"trace_dbm contains {trace.size - finite_count} non-finite values")
        start = float(saved["start_frequency_hz"])
        stop = float(saved["stop_frequency_hz"])
        center = float(saved["center_frequency_hz"])
        span = float(saved["span_hz"])
        metadata = (start, stop, center, span, float(saved["rbw_hz"]), float(saved["reference_level_dbm"]))
        if not all(math.isfinite(value) for value in metadata):
            raise ValueError("Saved frequency or amplitude metadata is non-finite")
        if stop <= start or span <= 0 or not math.isclose(stop - start, span, rel_tol=1e-9, abs_tol=1e-3):
            raise ValueError("Saved start/stop/span metadata is inconsistent")
        frequency_resolution = span / trace.size
        strongest = int(np.argmax(trace))
        return FrameSummary(
            shape=trace.shape,
            dtype=str(trace.dtype),
            finite_count=finite_count,
            minimum_dbm=float(np.min(trace)),
            maximum_dbm=float(np.max(trace)),
            mean_dbm=float(np.mean(trace, dtype=np.float64)),
            frequency_resolution_hz=frequency_resolution,
            strongest_bin_index=strongest,
            strongest_bin_frequency_hz=start + strongest * frequency_resolution,
            strongest_bin_amplitude_dbm=float(trace[strongest]),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a SAN-90 frame saved by test_san90_acquisition.py.")
    parser.add_argument("frame", type=Path, help="Saved .npz file")
    args = parser.parse_args()
    try:
        summary = inspect_frame(args.frame)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Frame inspection failed: {error}\n")
    print(f"array shape: {summary.shape}")
    print(f"dtype: {summary.dtype}")
    print(f"finite-value count: {summary.finite_count}")
    print(f"minimum: {summary.minimum_dbm:.3f} dBm")
    print(f"maximum: {summary.maximum_dbm:.3f} dBm")
    print(f"mean: {summary.mean_dbm:.3f} dBm")
    print(f"frequency resolution: {summary.frequency_resolution_hz:.6f} Hz")
    print(f"strongest-bin index: {summary.strongest_bin_index}")
    print(f"strongest-bin frequency: {summary.strongest_bin_frequency_hz:.3f} Hz")
    print(f"strongest-bin amplitude: {summary.strongest_bin_amplitude_dbm:.3f} dBm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
