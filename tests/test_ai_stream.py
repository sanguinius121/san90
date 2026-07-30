from __future__ import annotations

import queue
import socket
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from backend.ai_stream.config import AiStreamConfig
from backend.ai_stream.image_accumulator import AiImageAccumulator, raw_packet_to_dbm, resize_frequency_linear
from backend.ai_stream.image_publisher import AiImagePublisher
from backend.ai_stream.metrics import AiStreamMetrics
from backend.ai_stream.power_profiles import POWER_PROFILES, dbm_to_gray8, require_power_profile
from backend.ai_stream.preview import PreviewWriter
from backend.ai_stream.pipeline import AiStreamPipeline
from backend.ai_stream.protocol import PAYLOAD_SIZE, build_metadata, encode_metadata, validate_multipart
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata


def packet_metadata(last_sequence: int, last_timestamp_ns: int, mapping: RawAmplitudeMapping | None = None) -> RawTraceMetadata:
    return RawTraceMetadata(
        sequence=last_sequence,
        device_timestamp_ns=last_timestamp_ns,
        host_timestamp_ns=last_timestamp_ns,
        receipt_monotonic_ns=last_timestamp_ns,
        start_frequency_hz=2.39921875e9,
        center_frequency_hz=2.45e9,
        stop_frequency_hz=2.50078125e9,
        span_hz=101.5625e6,
        rbw_hz=60_306.091,
        reference_level_dbm=0.0,
        mapping=mapping or RawAmplitudeMapping(1.0, -130.0),
        configuration_generation=1,
    )


class PowerProfileTests(unittest.TestCase):
    def test_required_profiles_are_exact_and_unknown_is_rejected(self) -> None:
        self.assertEqual(
            {name: (profile.min_dbm, profile.max_dbm) for name, profile in POWER_PROFILES.items()},
            {"normal": (-130.0, -50.0), "external_lna": (-120.0, -20.0), "strong_signal": (-100.0, 0.0)},
        )
        with self.assertRaisesRegex(ValueError, "unknown AI power profile"):
            require_power_profile("adaptive")

    def test_configuration_is_fixed_640_and_target_is_7_to_10(self) -> None:
        self.assertEqual(AiStreamConfig().power_profile, "external_lna")
        with self.assertRaisesRegex(ValueError, "between 7 and 10"):
            AiStreamConfig(target_images_per_second=10.1)
        with self.assertRaisesRegex(ValueError, "exactly 640"):
            AiStreamConfig(image_width=320)


class ConversionTests(unittest.TestCase):
    def test_raw_to_dbm_uses_sdk_scale_and_offset(self) -> None:
        raw = np.array([[0, 1, 255], [10, 20, 30]], dtype=np.uint8)
        actual = raw_packet_to_dbm(raw, RawAmplitudeMapping(0.5, -120.0))
        np.testing.assert_allclose(actual, raw.astype(np.float32) * 0.5 - 120.0)
        self.assertEqual(actual.dtype, np.float32)

    def test_frequency_resize_equal_wider_and_narrower_preserves_endpoints(self) -> None:
        equal = np.arange(1280, dtype=np.float32).reshape(2, 640)
        np.testing.assert_array_equal(resize_frequency_linear(equal), equal)
        for source_width in (5, 1000):
            source = np.stack([
                np.linspace(-100, -20, source_width, dtype=np.float32),
                np.linspace(-90, -10, source_width, dtype=np.float32),
            ])
            resized = resize_frequency_linear(np.ascontiguousarray(source))
            self.assertEqual(resized.shape, (2, 640))
            np.testing.assert_allclose(resized[:, 0], source[:, 0])
            np.testing.assert_allclose(resized[:, -1], source[:, -1])
            self.assertAlmostEqual(float(resized[0, 320]), -100 + 80 * 320 / 639, places=4)

    def test_gray8_mapping_is_exact_for_every_profile(self) -> None:
        for profile in POWER_PROFILES.values():
            values = np.full((640, 640), (profile.min_dbm + profile.max_dbm) / 2, dtype=np.float32)
            values[0, :4] = [profile.min_dbm - 1, profile.min_dbm, profile.max_dbm, profile.max_dbm + 1]
            gray = dbm_to_gray8(values, profile.min_dbm, profile.max_dbm)
            self.assertEqual(gray.dtype, np.uint8)
            self.assertEqual(gray.shape, (640, 640))
            self.assertTrue(gray.flags.c_contiguous)
            self.assertEqual(len(gray.tobytes(order="C")), PAYLOAD_SIZE)
            self.assertEqual(gray[0].tolist()[:4], [0, 0, 255, 255])
            self.assertIn(int(gray[1, 1]), (127, 128))


class AccumulatorTests(unittest.TestCase):
    def make_accumulator(self, *, queue_size: int = 2, pool_size: int = 4, profile=None) -> tuple[AiImageAccumulator, AiStreamMetrics]:
        metrics = AiStreamMetrics()
        selected = profile or [POWER_PROFILES["external_lna"]]
        accumulator = AiImageAccumulator(
            target_images_per_second=10,
            queue_size=queue_size,
            buffer_pool_size=pool_size,
            profile_provider=lambda: selected[0],
            metrics=metrics,
        )
        accumulator.configure(128, 3, 1)
        return accumulator, metrics

    def feed_packet(self, accumulator: AiImageAccumulator, packet_index: int, *, row_base: int = 0) -> None:
        first = packet_index * 128
        rows = np.arange(row_base + first, row_base + first + 128, dtype=np.uint16) % 256
        raw = np.repeat(rows.astype(np.uint8)[:, None], 3, axis=1)
        accumulator.offer_packet(
            np.ascontiguousarray(raw),
            packet_metadata(first + 127, (first + 127) * 1_000_000),
            trace_timestamp_step_ns=1_000_000,
        )

    def test_exactly_640_rows_stay_chronological_across_packet_boundaries(self) -> None:
        accumulator, metrics = self.make_accumulator()
        for packet in range(5):
            self.feed_packet(accumulator, packet)
        completed = accumulator.completed.get_nowait()
        self.assertEqual(completed.capture.first_trace_sequence, 0)
        self.assertEqual(completed.capture.last_trace_sequence, 639)
        self.assertEqual(completed.capture.capture_start_timestamp_ns, 0)
        self.assertEqual(completed.capture.capture_end_timestamp_ns, 639_000_000)
        self.assertTrue(np.all(completed.buffer.dbm[0] == -130.0))
        self.assertTrue(np.all(completed.buffer.dbm[-1] == -3.0))
        snapshot = metrics.snapshot(queue_depth=0, free_buffer_count=0)
        self.assertEqual(snapshot["ai_traces_used_total"], 640)
        accumulator.release(completed.buffer)

    def test_capture_callback_and_timeline_namespace_support_epoch_correlation(self) -> None:
        captures = []
        metrics = AiStreamMetrics()
        accumulator = AiImageAccumulator(
            target_images_per_second=10,
            queue_size=2,
            buffer_pool_size=4,
            profile_provider=lambda: POWER_PROFILES["external_lna"],
            metrics=metrics,
            capture_callback=captures.append,
        )
        accumulator.configure(640, 1, 1)
        accumulator.reset_timeline(17)
        accumulator.offer_packet(
            np.full((640, 1), 20, dtype=np.uint8),
            packet_metadata(639, 639_000_000),
            trace_timestamp_step_ns=1_000_000,
        )
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0].sequence, 17 << 32)
        accumulator.reset_timeline(18)
        self.assertEqual(accumulator.queue_depth, 0)

    def test_packet_can_complete_one_image_and_begin_the_next(self) -> None:
        accumulator, _ = self.make_accumulator()
        for packet in range(6):
            self.feed_packet(accumulator, packet)
        first = accumulator.completed.get_nowait()
        self.assertEqual((first.capture.first_trace_sequence, first.capture.last_trace_sequence), (0, 639))
        self.assertEqual(accumulator._window_position, 128)
        accumulator.release(first.buffer)

    def test_profile_change_applies_only_to_new_images(self) -> None:
        selected = [POWER_PROFILES["normal"]]
        accumulator, _ = self.make_accumulator(profile=selected)
        for packet in range(5):
            self.feed_packet(accumulator, packet)
        selected[0] = POWER_PROFILES["strong_signal"]
        for packet in range(5, 10):
            self.feed_packet(accumulator, packet)
        first = accumulator.completed.get_nowait()
        second = accumulator.completed.get_nowait()
        self.assertEqual(first.capture.power_profile.name, "normal")
        self.assertEqual(second.capture.power_profile.name, "strong_signal")
        accumulator.release(first.buffer)
        accumulator.release(second.buffer)

    def test_full_queue_drops_oldest_and_retains_latest_without_blocking(self) -> None:
        accumulator, metrics = self.make_accumulator(queue_size=1, pool_size=3)
        started = time.perf_counter()
        for packet in range(10):
            self.feed_packet(accumulator, packet)
        self.assertLess(time.perf_counter() - started, 1.0)
        retained = accumulator.completed.get_nowait()
        self.assertEqual(retained.capture.sequence, 1)
        snapshot = metrics.snapshot(queue_depth=0, free_buffer_count=0)
        self.assertEqual(snapshot["ai_images_dropped_queue_total"], 1)
        accumulator.release(retained.buffer)

    def test_deterministic_window_scheduler_reaches_ten_images_per_second_at_7600_traces(self) -> None:
        metrics = AiStreamMetrics()
        accumulator = AiImageAccumulator(
            target_images_per_second=10,
            queue_size=2,
            buffer_pool_size=4,
            profile_provider=lambda: POWER_PROFILES["external_lna"],
            metrics=metrics,
        )
        accumulator.configure(100, 1, 1)
        step_ns = round(1e9 / 7600)
        sent = 0
        for packet_index in range(760):
            first = packet_index * 100
            raw = np.full((100, 1), 30, dtype=np.uint8)
            accumulator.offer_packet(
                raw,
                packet_metadata(first + 99, (first + 99) * step_ns),
                trace_timestamp_step_ns=step_ns,
            )
            while True:
                try:
                    completed = accumulator.completed.get_nowait()
                except queue.Empty:
                    break
                sent += 1
                accumulator.release(completed.buffer)
        self.assertGreaterEqual(sent, 98)
        self.assertLessEqual(sent, 101)
        snapshot = metrics.snapshot(queue_depth=0, free_buffer_count=accumulator.free_buffer_count)
        self.assertGreater(snapshot["ai_traces_skipped_rate_limit_total"], 0)

    def test_no_free_buffer_drops_ai_window_without_waiting(self) -> None:
        metrics = AiStreamMetrics()
        accumulator = AiImageAccumulator(
            target_images_per_second=10,
            queue_size=2,
            buffer_pool_size=2,
            profile_provider=lambda: POWER_PROFILES["external_lna"],
            metrics=metrics,
        )
        accumulator.configure(640, 1, 1)
        raw = np.full((640, 1), 20, dtype=np.uint8)
        for index in range(3):
            first = index * 640
            accumulator.offer_packet(
                raw,
                packet_metadata(first + 639, (first + 639) * 1_000_000),
                trace_timestamp_step_ns=1_000_000,
            )
        snapshot = metrics.snapshot(queue_depth=accumulator.queue_depth, free_buffer_count=accumulator.free_buffer_count)
        self.assertEqual(snapshot["ai_images_dropped_no_buffer_total"], 1)
        self.assertEqual(snapshot["ai_queue_depth"], 2)

    def test_seven_image_per_second_configuration_is_scheduled_deterministically(self) -> None:
        metrics = AiStreamMetrics()
        accumulator = AiImageAccumulator(
            target_images_per_second=7,
            queue_size=2,
            buffer_pool_size=4,
            profile_provider=lambda: POWER_PROFILES["external_lna"],
            metrics=metrics,
        )
        accumulator.configure(100, 1, 1)
        step_ns = round(1e9 / 7600)
        created = 0
        for packet_index in range(760):
            first = packet_index * 100
            accumulator.offer_packet(
                np.full((100, 1), 20, dtype=np.uint8),
                packet_metadata(first + 99, (first + 99) * step_ns),
                trace_timestamp_step_ns=step_ns,
            )
            while accumulator.queue_depth:
                image = accumulator.completed.get_nowait()
                created += 1
                accumulator.release(image.buffer)
        self.assertGreaterEqual(created, 68)
        self.assertLessEqual(created, 71)


class ProtocolPreviewPublisherTests(unittest.TestCase):
    def make_completed(self):
        accumulator = AiImageAccumulator(
            target_images_per_second=10,
            queue_size=2,
            buffer_pool_size=4,
            profile_provider=lambda: POWER_PROFILES["external_lna"],
            metrics=AiStreamMetrics(),
        )
        accumulator.configure(640, 640, 4)
        raw = np.full((640, 640), 80, dtype=np.uint8)
        accumulator.offer_packet(raw, packet_metadata(8_000_639, 1_784_600_000_100_000_000), trace_timestamp_step_ns=100_000)
        return accumulator, accumulator.completed.get_nowait()

    def test_metadata_and_two_part_payload_reconstruct_exactly(self) -> None:
        accumulator, completed = self.make_completed()
        metadata = build_metadata(completed.capture, completed.buffer.dbm)
        gray = dbm_to_gray8(completed.buffer.dbm, -120, -20)
        metadata_bytes = encode_metadata(metadata)
        decoded, reconstructed = validate_multipart(metadata_bytes, gray.tobytes(order="C"))
        self.assertEqual(decoded["payload_size_bytes"], 409600)
        self.assertEqual(decoded["first_trace_sequence"], 8_000_000)
        self.assertEqual(decoded["last_trace_sequence"], 8_000_639)
        self.assertEqual(decoded["frame_width_source"], 640)
        self.assertAlmostEqual(decoded["db_per_gray_level"], 100 / 255)
        np.testing.assert_array_equal(reconstructed, gray)
        with self.assertRaisesRegex(ValueError, "exactly 409600"):
            validate_multipart(metadata_bytes, gray.tobytes()[:-1])
        accumulator.release(completed.buffer)

    def test_clipping_statistics_cover_weak_and_strong_signals_without_changing_profile(self) -> None:
        accumulator, completed = self.make_completed()
        completed.buffer.dbm.fill(-70.0)
        completed.buffer.dbm[0, :4] = [-140.0, -120.0, -20.0, 1.0]
        metadata = build_metadata(completed.capture, completed.buffer.dbm)
        self.assertEqual(metadata["power_profile"], "external_lna")
        self.assertEqual(metadata["power_min_dbm"], -120.0)
        self.assertEqual(metadata["power_max_dbm"], -20.0)
        self.assertEqual(metadata["image_min_dbm"], -140.0)
        self.assertEqual(metadata["image_max_dbm"], 1.0)
        self.assertGreater(metadata["clipped_low_ratio"], 0)
        self.assertGreater(metadata["clipped_high_ratio"], 0)
        accumulator.release(completed.buffer)

    def test_preview_is_lossless_rate_limited_and_rotated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = PreviewWriter(Path(directory), 1.0, 2)
            image = np.arange(640 * 640, dtype=np.uint32).reshape(640, 640).astype(np.uint8)
            metadata = {"sequence": 1, "power_profile": "normal", "center_frequency_hz": 2.45e9, "timestamp_ns": 1}
            saved, _ = writer.maybe_save(image, metadata)
            self.assertTrue(saved)
            self.assertFalse(writer.maybe_save(image, metadata)[0])
            for sequence in (2, 3):
                writer._last_saved = 0.0
                metadata = dict(metadata, sequence=sequence, timestamp_ns=sequence)
                writer.maybe_save(image, metadata)
            files = sorted(Path(directory).glob("*.png"))
            self.assertEqual(len(files), 2)
            with Image.open(files[-1]) as preview:
                self.assertEqual(preview.mode, "L")
                loaded = np.asarray(preview).copy()
            np.testing.assert_array_equal(loaded, image)

    def test_send_failure_returns_buffer_and_never_raises(self) -> None:
        accumulator, completed = self.make_completed()
        config = AiStreamConfig(enabled=True)
        metrics = accumulator.metrics
        publisher = AiImagePublisher(config, accumulator, metrics)

        class Again(Exception):
            pass

        class FakeZmq:
            NOBLOCK = 1

        FakeZmq.Again = Again

        class NoReceiverSocket:
            def send_multipart(self, *args, **kwargs):
                raise Again()

        before = accumulator.free_buffer_count
        publisher._publish_one(NoReceiverSocket(), FakeZmq, completed)
        self.assertEqual(accumulator.free_buffer_count, before + 1)
        self.assertEqual(metrics.snapshot(queue_depth=0, free_buffer_count=0)["ai_images_dropped_send_total"], 1)

    def test_successful_transport_is_exactly_two_parts(self) -> None:
        accumulator, completed = self.make_completed()
        publisher = AiImagePublisher(AiStreamConfig(enabled=True), accumulator, accumulator.metrics)

        class FakeZmq:
            NOBLOCK = 1
            class Again(Exception):
                pass

        class CapturingSocket:
            parts = None
            def send_multipart(self, parts, **kwargs):
                self.parts = [bytes(part) for part in parts]

        socket_capture = CapturingSocket()
        publisher._publish_one(socket_capture, FakeZmq, completed)
        self.assertIsNotNone(socket_capture.parts)
        self.assertEqual(len(socket_capture.parts), 2)
        _, reconstructed = validate_multipart(*socket_capture.parts)
        self.assertEqual(reconstructed.shape, (640, 640))

    def test_real_zmq_without_receiver_drops_without_blocking_or_crashing(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = AiStreamConfig(bind=f"tcp://127.0.0.1:{port}", send_timeout_ms=1)
        pipeline = AiStreamPipeline(config)
        pipeline.start()
        try:
            pipeline.configure(640, 640, 1)
            raw = np.full((640, 640), 50, dtype=np.uint8)
            started = time.perf_counter()
            pipeline.offer_packet(raw, packet_metadata(639, 639_000_000), trace_timestamp_step_ns=1_000_000)
            self.assertLess(time.perf_counter() - started, 0.25)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and pipeline.status()["ai_images_dropped_send_total"] == 0:
                time.sleep(0.01)
            status = pipeline.status()
            self.assertTrue(status["bound"])
            self.assertEqual(status["ai_images_dropped_send_total"], 1)
            self.assertEqual(status["ai_queue_depth"], 0)
        finally:
            pipeline.stop()

    def test_invalid_profile_retains_last_valid_profile(self) -> None:
        pipeline = AiStreamPipeline(AiStreamConfig(enabled=False, power_profile="normal"))
        with self.assertRaises(ValueError):
            pipeline.set_power_profile("unknown")
        self.assertEqual(pipeline.status()["active_power_profile"], "normal")


if __name__ == "__main__":
    unittest.main()
