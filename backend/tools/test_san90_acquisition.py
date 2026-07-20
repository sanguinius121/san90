#!/usr/bin/env python3
"""Standalone SAN-90 RTA acquisition, validation, and profiling diagnostic."""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analyzer.errors import AnalyzerError  # noqa: E402
from backend.analyzer.models import AnalyzerSettings, DeviceInfo, SpectrumFrame  # noqa: E402
from backend.analyzer.san90 import San90Diagnostics, San90Source  # noqa: E402


@dataclass(slots=True)
class ConsumerMetrics:
    observed_frames: int = 0
    invalid_frames: int = 0
    non_finite_frames: int = 0
    sequence_gaps: int = 0
    last_sequence: int | None = None
    last_frame: SpectrumFrame | None = None
    last_received_monotonic: float | None = None
    statistics_calls: int = 0
    statistics_total_s: float = 0.0
    statistics_max_s: float = 0.0

    def observe(self, frame: SpectrumFrame, expected_points: int) -> None:
        started = time.perf_counter()
        valid_shape = frame.values.ndim == 1 and frame.values.size == expected_points
        valid_type = frame.values.dtype == np.float32 and frame.values.flags.c_contiguous
        finite = bool(np.isfinite(frame.values).all()) if valid_shape else False
        if not valid_shape or not valid_type:
            self.invalid_frames += 1
        if not finite:
            self.non_finite_frames += 1
        if not valid_shape or not valid_type or not finite:
            raise RuntimeError(
                f"Invalid trace sequence {frame.sequence}: shape={frame.values.shape}, "
                f"dtype={frame.values.dtype}, contiguous={frame.values.flags.c_contiguous}, finite={finite}"
            )
        if self.last_sequence is not None and frame.sequence > self.last_sequence + 1:
            self.sequence_gaps += frame.sequence - self.last_sequence - 1
        elif self.last_sequence is not None and frame.sequence <= self.last_sequence:
            self.invalid_frames += 1
            raise RuntimeError(f"Non-monotonic trace sequence {frame.sequence} after {self.last_sequence}")
        self.last_sequence = frame.sequence
        self.last_frame = frame
        self.last_received_monotonic = time.monotonic()
        self.observed_frames += 1
        elapsed = time.perf_counter() - started
        self.statistics_calls += 1
        self.statistics_total_s += elapsed
        self.statistics_max_s = max(self.statistics_max_s, elapsed)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone HAROGIC SAN-90 RTA acquisition diagnostic (no web server)."
    )
    parser.add_argument("--device-index", type=int, default=0, help="Zero-based index among discovered SAN-90 devices.")
    parser.add_argument("--center-hz", type=float, default=1.0e9, help="Requested RTA center frequency in Hz.")
    parser.add_argument(
        "--span-hz", type=float, default=100.0e6,
        help="Requested instantaneous span target. RTA has no direct span field; actual start/stop are reported.",
    )
    parser.add_argument("--rbw-hz", type=float, default=None, help="Manual RBW in Hz; omit to retain the SDK default.")
    parser.add_argument(
        "--reference-level-dbm", type=float, default=0.0,
        help="Requested reference level in dBm. This is not an RF damage limit.",
    )
    parser.add_argument("--attenuation-db", type=int, default=None, help="Attenuation in dB; omit for SDK automatic mode.")
    parser.add_argument(
        "--preamplifier", choices=("off", "auto", "low", "medium", "high"), default="off",
        help="Preamplifier mode; forced off is the conservative default.",
    )
    parser.add_argument("--duration", type=float, default=5.0, help="Acquisition duration in seconds.")
    parser.add_argument("--mode", choices=("rta",), default="rta", help="SDK measurement mode (RTA only).")
    parser.add_argument("--stats-interval", type=float, default=1.0, help="Periodic report interval in seconds.")
    parser.add_argument("--save-first-frame", type=Path, default=None, metavar="FILE.npz")
    parser.add_argument("--profile", action="store_true", help="Report lightweight SDK and NumPy timing measurements.")
    parser.add_argument("--library", type=Path, default=None, help="Explicit libhtraapi.so.0.55.88 path.")
    args = parser.parse_args()
    if args.device_index < 0:
        parser.error("--device-index must be non-negative")
    for name in ("center_hz", "span_hz", "duration", "stats_interval"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.rbw_hz is not None and (not math.isfinite(args.rbw_hz) or args.rbw_hz <= 0):
        parser.error("--rbw-hz must be finite and positive")
    if not math.isfinite(args.reference_level_dbm):
        parser.error("--reference-level-dbm must be finite")
    return args


def _format_optional(value: float | int | str | None, suffix: str = "") -> str:
    return "SDK default" if value is None else f"{value}{suffix}"


def print_startup(
    device: DeviceInfo,
    device_index: int,
    requested: argparse.Namespace,
    actual: AnalyzerSettings,
    point_count: int,
) -> None:
    actual_span = float(actual.span_hz or 0.0)
    start = actual.center_frequency_hz - actual_span / 2.0
    stop = actual.center_frequency_hz + actual_span / 2.0
    print("SAN-90 device:")
    print(f"  model: {device.model} (code {device.model_code})")
    print(f"  serial: {device.serial}")
    print(f"  device index: {device_index}")
    print("  interface: USB")
    print(f"  API version: {device.sdk_version}")
    print(f"  MCU version: {device.firmware_version}")
    print(f"  FPGA version: {device.fpga_version}")
    print("\nRequested measurement:")
    print(f"  mode: {requested.mode}")
    print(f"  center frequency: {requested.center_hz:.3f} Hz")
    print(f"  span target: {requested.span_hz:.3f} Hz (RTA has no direct span field)")
    print(f"  RBW: {_format_optional(requested.rbw_hz, ' Hz')}")
    print(f"  reference level: {requested.reference_level_dbm:.2f} dBm")
    print(f"  attenuation: {_format_optional(requested.attenuation_db, ' dB')}")
    print(f"  preamplifier: {requested.preamplifier}")
    print("\nActual measurement:")
    print(f"  center frequency: {actual.center_frequency_hz:.3f} Hz")
    print(f"  start frequency: {start:.3f} Hz")
    print(f"  stop frequency: {stop:.3f} Hz")
    print(f"  span: {actual_span:.3f} Hz")
    print(f"  RBW: {float(actual.rbw_hz or 0.0):.3f} Hz")
    print(f"  point count: {point_count}")
    print("  data type: float32 (converted from SDK uint8)")
    print("  amplitude unit: dBm")
    attenuation = "automatic (-1 SDK sentinel)" if actual.attenuation_db == -1 else f"{actual.attenuation_db} dB"
    print(f"  attenuation: {attenuation}")
    print(f"  preamplifier: {actual.preamplifier}")
    if abs(actual_span - requested.span_hz) / requested.span_hz > 0.05:
        print("  warning: actual RTA span differs from the requested span target by more than 5%")


def save_first_frame(path: Path, frame: SpectrumFrame, device: DeviceInfo, actual: AnalyzerSettings) -> Path:
    destination = path if path.suffix.lower() == ".npz" else path.with_suffix(".npz")
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        trace_dbm=np.array(frame.values, dtype=np.float32, order="C", copy=True),
        start_frequency_hz=np.float64(frame.start_frequency_hz),
        stop_frequency_hz=np.float64(frame.stop_frequency_hz),
        center_frequency_hz=np.float64(frame.center_frequency_hz),
        span_hz=np.float64(frame.span_hz),
        rbw_hz=np.float64(frame.rbw_hz),
        vbw_hz=np.float64(np.nan if frame.vbw_hz is None else frame.vbw_hz),
        reference_level_dbm=np.float64(frame.reference_level_dbm),
        timestamp_ns=np.uint64(frame.timestamp_ns),
        sequence=np.uint64(frame.sequence),
        point_count=np.uint32(frame.point_count),
        frame_type=np.str_(frame.frame_type.value),
        device_model=np.str_(device.model),
        device_model_code=np.int32(device.model_code if device.model_code is not None else -1),
        device_serial=np.str_(device.serial),
        api_version=np.str_(device.sdk_version or ""),
        mcu_version=np.str_(device.firmware_version or ""),
        fpga_version=np.str_(device.fpga_version or ""),
        measurement_mode=np.str_(actual.mode),
    )
    return destination


def print_periodic(
    elapsed: float,
    status_frames: int,
    point_count: int,
    diagnostics: San90Diagnostics,
    consumer: ConsumerMetrics,
    replaced: int,
    acquisition_errors: int,
) -> None:
    rate = status_frames / elapsed if elapsed > 0 else 0.0
    point_rate = rate * point_count
    age_ms = None
    if consumer.last_received_monotonic is not None:
        age_ms = max(0.0, (time.monotonic() - consumer.last_received_monotonic) * 1000.0)
    print(f"\nRuntime {elapsed:.1f} s:")
    print(f"  SDK trace frames received: {status_frames}")
    print(f"  frames observed by diagnostic: {consumer.observed_frames}")
    print(f"  acquisition rate: {rate:.1f} frames/s")
    print(f"  effective point rate: {point_rate / 1e6:.2f} Mpoints/s")
    print(f"  point count: {point_count}")
    print(f"  minimum: {_format_db(diagnostics.minimum_dbm)}")
    print(f"  maximum: {_format_db(diagnostics.maximum_dbm)}")
    print(f"  mean: {_format_db(diagnostics.mean_dbm)}")
    print(f"  standard deviation: {_format_db(diagnostics.standard_deviation_db, ' dB')}")
    print(f"  non-finite frames: {consumer.non_finite_frames}")
    print(f"  timeouts: {diagnostics.timeouts}")
    print(f"  sequence gaps (intentionally skipped latest frames): {consumer.sequence_gaps}")
    print(f"  frames replaced before consumption: {replaced}")
    print(f"  acquisition errors: {acquisition_errors}")
    print(f"  last frame age: {'n/a' if age_ms is None else f'{age_ms:.3f} ms'}")


def _format_db(value: float | None, suffix: str = " dBm") -> str:
    return "n/a" if value is None else f"{value:.3f}{suffix}"


def _average_ms(total_s: float, calls: int) -> float:
    return total_s * 1000.0 / calls if calls else 0.0


def print_profile(diagnostics: San90Diagnostics, consumer: ConsumerMetrics, cpu_percent: float) -> None:
    snapshot_calls = diagnostics.display_snapshots_created
    print("\nProfiling:")
    print(f"  Python process CPU: {cpu_percent:.1f}% of one core")
    print(
        f"  SDK blocking read: avg {_average_ms(diagnostics.sdk_read_total_s, diagnostics.sdk_read_calls):.4f} ms, "
        f"max {diagnostics.sdk_read_max_s * 1000.0:.4f} ms ({diagnostics.sdk_read_calls} calls)"
    )
    print(
        f"  native latest/max copy: avg {_average_ms(diagnostics.native_copy_total_s, diagnostics.packets_received):.4f} ms, "
        f"max {diagnostics.native_copy_max_s * 1000.0:.4f} ms"
    )
    print(
        f"  display uint8-to-float32 conversion: avg {_average_ms(diagnostics.display_conversion_total_s, snapshot_calls):.4f} ms, "
        f"max {diagnostics.display_conversion_max_s * 1000.0:.4f} ms"
    )
    print(
        f"  display snapshot creation: avg {_average_ms(diagnostics.snapshot_total_s, snapshot_calls):.4f} ms, "
        f"max {diagnostics.snapshot_max_s * 1000.0:.4f} ms ({snapshot_calls} snapshots)"
    )
    print(
        f"  packet validation: avg {_average_ms(diagnostics.validation_total_s, diagnostics.packets_received):.4f} ms, "
        f"max {diagnostics.validation_max_s * 1000.0:.4f} ms"
    )
    print(
        f"  acquisition statistics: avg {_average_ms(diagnostics.statistics_total_s, diagnostics.packets_received):.4f} ms, "
        f"max {diagnostics.statistics_max_s * 1000.0:.4f} ms"
    )
    print(
        f"  consumer validation/statistics: avg {_average_ms(consumer.statistics_total_s, consumer.statistics_calls):.4f} ms, "
        f"max {consumer.statistics_max_s * 1000.0:.4f} ms"
    )


def print_overall(
    elapsed: float,
    point_count: int,
    diagnostics: San90Diagnostics,
    consumer: ConsumerMetrics,
    replaced: int,
    acquisition_errors: int,
    cpu_percent: float,
    profile: bool,
) -> None:
    total_frames = diagnostics.trace_frames_received
    print("\nOverall summary:")
    print(f"  elapsed time: {elapsed:.3f} s")
    print(f"  total SDK trace frames: {total_frames}")
    print(f"  mean acquisition FPS: {total_frames / elapsed if elapsed > 0 else 0.0:.2f}")
    print(f"  effective point rate: {(total_frames * point_count / elapsed) / 1e6 if elapsed > 0 else 0.0:.2f} Mpoints/s")
    print(f"  minimum observed trace value: {_format_db(diagnostics.minimum_dbm)}")
    print(f"  maximum observed trace value: {_format_db(diagnostics.maximum_dbm)}")
    print(f"  timeout count: {diagnostics.timeouts}")
    print(f"  invalid-frame count: {consumer.invalid_frames + diagnostics.invalid_packets}")
    print(f"  non-finite-frame count: {consumer.non_finite_frames}")
    print(f"  sequence-gap count: {consumer.sequence_gaps}")
    print(f"  intentionally replaced frames: {replaced}")
    print(f"  acquisition errors: {acquisition_errors}")
    if profile:
        print_profile(diagnostics, consumer, cpu_percent)


def main() -> int:
    args = parse_args()
    source: San90Source | None = None
    consumer = ConsumerMetrics()
    started = 0.0
    process_started = 0.0
    exit_code = 0
    failure: BaseException | None = None
    interrupted = False
    point_count = 0
    first_frame_saved = False
    try:
        source = San90Source(device_index=args.device_index, library_path=args.library)
        source.connect()
        device = source.get_device_info()
        if device is None:
            raise RuntimeError("SAN-90 connected without device information")
        requested_settings = AnalyzerSettings(
            mode=args.mode,
            center_frequency_hz=args.center_hz,
            span_hz=None,  # RTA_Profile_TypeDef has no direct span field.
            rbw_hz=args.rbw_hz,
            reference_level_dbm=args.reference_level_dbm,
            attenuation_db=args.attenuation_db,
            preamplifier=args.preamplifier,
        )
        actual = source.apply_settings(requested_settings)
        point_counts = source.get_capabilities().native_point_counts
        if len(point_counts) != 1 or point_counts[0] <= 0:
            raise RuntimeError(f"Invalid RTA point-count metadata: {point_counts}")
        point_count = point_counts[0]
        print_startup(device, args.device_index, args, actual, point_count)

        source.start()
        started = time.monotonic()
        process_started = time.process_time()
        deadline = started + args.duration
        next_report = started + args.stats_interval
        while time.monotonic() < deadline:
            frame = source.read_frame()
            if frame is not None:
                consumer.observe(frame, point_count)
                if args.save_first_frame is not None and not first_frame_saved:
                    saved = save_first_frame(args.save_first_frame, frame, device, actual)
                    print(f"\nSaved first frame: {saved}")
                    first_frame_saved = True
            now = time.monotonic()
            status = source.get_status()
            if not status.acquisition_running and status.last_error:
                raise RuntimeError(status.last_error)
            if now >= next_report:
                print_periodic(
                    now - started,
                    status.sdk_frames_received,
                    point_count,
                    source.get_diagnostics(),
                    consumer,
                    status.frames_replaced,
                    status.acquisition_errors,
                )
                next_report += args.stats_interval
            if frame is None:
                time.sleep(0.0005)
        if consumer.observed_frames == 0:
            raise RuntimeError("No spectrum frame was received during the requested duration")
    except KeyboardInterrupt:
        interrupted = True
        exit_code = 130
        print("\nCtrl+C received; stopping acquisition.")
    except (AnalyzerError, RuntimeError, OSError, ValueError) as error:
        failure = error
        exit_code = 1
    finally:
        if source is not None:
            try:
                source.stop()
            except AnalyzerError as cleanup_error:
                print(f"SAN-90 stop failed: {cleanup_error}", file=sys.stderr)
                if failure is None and not interrupted:
                    exit_code = 1
            elapsed = max(0.0, time.monotonic() - started) if started else 0.0
            cpu_elapsed = max(0.0, time.process_time() - process_started) if process_started else 0.0
            status = source.get_status()
            diagnostics = source.get_diagnostics()
            if started:
                print_overall(
                    elapsed,
                    point_count,
                    diagnostics,
                    consumer,
                    status.frames_replaced,
                    status.acquisition_errors,
                    100.0 * cpu_elapsed / elapsed if elapsed > 0 else 0.0,
                    args.profile,
                )
            try:
                source.disconnect()
            except AnalyzerError as cleanup_error:
                print(f"SAN-90 close failed: {cleanup_error}", file=sys.stderr)
                if failure is None and not interrupted:
                    exit_code = 1
    if failure is not None:
        print(f"SAN-90 diagnostic failed: {failure}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
