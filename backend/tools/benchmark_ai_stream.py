#!/usr/bin/env python3
"""Hardware-independent 7,600-trace/s display + AI branch benchmark."""

from __future__ import annotations

import argparse
import json
import queue
import resource
import sys
import threading
import time
from pathlib import Path

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ai_stream.image_accumulator import AiImageAccumulator
from backend.ai_stream.metrics import AiStreamMetrics
from backend.ai_stream.power_profiles import POWER_PROFILES, dbm_to_gray8
from backend.ai_stream.protocol import build_metadata
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.spectrum_temporal import NativeSpectrumTemporalAccumulator
from backend.analyzer.waterfall import TimedWaterfallBatchProducer, WaterfallRateConfig


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=60.0, help="Use 600 for the required ten-minute soak")
    parser.add_argument("--trace-rate", type=float, default=7600.0)
    parser.add_argument("--target-images-per-second", type=float, default=10.0)
    parser.add_argument("--packet-frames", type=int, default=128)
    parser.add_argument("--frame-width", type=int, default=3328)
    return parser.parse_args()


def current_rss_mib() -> float:
    with open("/proc/self/statm", encoding="ascii") as handle:
        resident_pages = int(handle.read().split()[1])
    return resident_pages * resource.getpagesize() / (1024 * 1024)


def main() -> int:
    args = arguments()
    if args.duration <= 0 or args.trace_rate <= 0 or args.packet_frames <= 0 or args.frame_width <= 0:
        raise SystemExit("duration, trace rate, and packet dimensions must be positive")
    metrics = AiStreamMetrics()
    accumulator = AiImageAccumulator(
        target_images_per_second=args.target_images_per_second,
        queue_size=2,
        buffer_pool_size=4,
        profile_provider=lambda: POWER_PROFILES["external_lna"],
        metrics=metrics,
    )
    accumulator.configure(args.packet_frames, args.frame_width, 1)
    spectrum = NativeSpectrumTemporalAccumulator(args.frame_width)
    waterfall = TimedWaterfallBatchProducer(args.frame_width, 1, WaterfallRateConfig(60.0, 60.0, 1))
    stop_consumer = threading.Event()

    def consume() -> None:
        while not stop_consumer.is_set() or accumulator.queue_depth:
            try:
                image = accumulator.completed.get(timeout=0.05)
            except queue.Empty:
                continue
            build_metadata(image.capture, image.buffer.dbm)
            dbm_to_gray8(
                image.buffer.dbm,
                image.capture.power_profile.min_dbm,
                image.capture.power_profile.max_dbm,
                output=image.buffer.gray8,
                workspace=image.buffer.workspace,
            )
            metrics.increment("ai_images_sent_total")
            accumulator.release(image.buffer)

    consumer = threading.Thread(target=consume, name="ai-benchmark-consumer", daemon=True)
    consumer.start()
    raw = np.full((args.packet_frames, args.frame_width), 55, dtype=np.uint8)
    x = np.arange(args.frame_width)
    raw[:, np.abs(x - args.frame_width * 0.35) < max(1, args.frame_width * 0.003)] = 170
    raw[:, np.abs(x - args.frame_width * 0.65) < max(1, args.frame_width * 0.05)] = 110
    mapping = RawAmplitudeMapping(0.5, -130.0)
    step_ns = round(1e9 / args.trace_rate)
    packet_period = args.packet_frames / args.trace_rate
    sequence = 0
    spectrum_frames = 0
    waterfall_batches = 0
    start_rss = current_rss_mib()
    start_cpu = time.process_time()
    started = time.monotonic()
    deadline = started
    try:
        while time.monotonic() - started < args.duration:
            # Periodic one-trace FHSS event survives the existing temporal maxima.
            raw[sequence % args.packet_frames, :] = 55
            hop = (sequence // args.packet_frames) % 5
            hop_center = int(args.frame_width * (0.12 + hop * 0.18))
            raw[sequence % args.packet_frames, max(0, hop_center - 2):hop_center + 3] = 210
            packet_first_timestamp = sequence * step_ns
            last_sequence = sequence + args.packet_frames - 1
            receipt = time.monotonic_ns()
            metadata = RawTraceMetadata(
                sequence=last_sequence,
                device_timestamp_ns=packet_first_timestamp + (args.packet_frames - 1) * step_ns,
                host_timestamp_ns=time.time_ns(),
                receipt_monotonic_ns=receipt,
                start_frequency_hz=2.39921875e9,
                center_frequency_hz=2.45e9,
                stop_frequency_hz=2.50078125e9,
                span_hz=101.5625e6,
                rbw_hz=60_306.091,
                reference_level_dbm=0.0,
                mapping=mapping,
                configuration_generation=1,
            )
            if spectrum.add_packet(raw, metadata) is not None:
                spectrum_frames += 1
            waterfall.add_packet(raw, metadata, trace_timestamp_step_ns=step_ns)
            batch = waterfall.exchange.take_latest()
            if batch is not None:
                waterfall_batches += 1
            accumulator.offer_packet(raw, metadata, trace_timestamp_step_ns=step_ns)
            sequence += args.packet_frames
            deadline += packet_period
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
    finally:
        stop_consumer.set()
        consumer.join(timeout=3.0)
    elapsed = time.monotonic() - started
    snapshot = metrics.snapshot(queue_depth=accumulator.queue_depth, free_buffer_count=accumulator.free_buffer_count)
    waterfall_metrics = waterfall.metrics()
    result = {
        "elapsed_seconds": elapsed,
        "input_traces": sequence,
        "acquisition_traces_per_second": sequence / elapsed,
        "spectrum_frames_per_second": spectrum_frames / elapsed,
        "waterfall_rows_per_second": waterfall_metrics.completed_rows / elapsed,
        "waterfall_batches_per_second": waterfall_batches / elapsed,
        "ai_images_per_second": snapshot["ai_images_sent_total"] / elapsed,
        "ai_images_created_total": snapshot["ai_images_created_total"],
        "ai_images_sent_total": snapshot["ai_images_sent_total"],
        "ai_images_dropped_queue_total": snapshot["ai_images_dropped_queue_total"],
        "ai_images_dropped_no_buffer_total": snapshot["ai_images_dropped_no_buffer_total"],
        "ai_queue_depth": snapshot["ai_queue_depth"],
        "ai_free_buffer_count": snapshot["ai_free_buffer_count"],
        "process_cpu_percent_of_one_core": 100.0 * (time.process_time() - start_cpu) / elapsed,
        "rss_start_mib": start_rss,
        "rss_end_mib": current_rss_mib(),
    }
    print(json.dumps(result, indent=2))
    passed = (
        result["acquisition_traces_per_second"] >= args.trace_rate * 0.98
        and 58.0 <= result["spectrum_frames_per_second"] <= 62.0
        and 58.0 <= result["waterfall_rows_per_second"] <= 62.0
        and 7.0 <= result["ai_images_per_second"] <= 10.2
        and result["ai_queue_depth"] <= 2
        and result["ai_images_dropped_no_buffer_total"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
