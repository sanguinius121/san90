from __future__ import annotations

import asyncio
import io
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException
from PIL import Image

import backend.main as backend_main
from backend.ai_stream.power_profiles import POWER_PROFILES
from backend.ai_stream.preview import AiPreviewEncoder, AiPreviewSnapshot, LatestAiPreviewStore
from backend.ai_stream.protocol import CaptureMetadata


def capture(
    sequence: int,
    *,
    source: str = "hardware",
    epoch: int | None = None,
    config_id: int | None = None,
) -> CaptureMetadata:
    return CaptureMetadata(
        sequence=sequence,
        first_trace_sequence=1,
        last_trace_sequence=640,
        capture_start_timestamp_ns=1_000,
        capture_end_timestamp_ns=2_000 + sequence,
        center_frequency_hz=2.45e9,
        start_frequency_hz=2.39921875e9,
        stop_frequency_hz=2.50078125e9,
        frame_width_source=3328,
        configuration_generation=7,
        power_profile=POWER_PROFILES["external_lna"],
        preview_source=source,
        playback_epoch=epoch,
        config_id=config_id,
    )


def snapshot(sequence: int = 1) -> AiPreviewSnapshot:
    return AiPreviewSnapshot(
        sequence=sequence,
        source="hardware",
        playback_epoch=None,
        config_id=None,
        configuration_generation=7,
        center_frequency_hz=2.45e9,
        frequency_start_hz=2.39921875e9,
        frequency_stop_hz=2.50078125e9,
        width=640,
        height=640,
        created_at_ns=2_001,
        content_type="image/png",
        image=b"png",
    )


class LatestPreviewStoreTests(unittest.TestCase):
    def test_initial_replace_clear_and_sequence_safe_read(self) -> None:
        store = LatestAiPreviewStore()
        self.assertFalse(store.status(source="hardware")["available"])
        first = snapshot(1)
        second = snapshot(2)
        store.publish(first)
        self.assertIs(store.image_for_sequence(1), first)
        store.publish(second)
        self.assertIsNone(store.image_for_sequence(1))
        self.assertIs(store.image_for_sequence(2), second)
        store.clear("playback_ai_disabled")
        status = store.status(source="playback")
        self.assertFalse(status["available"])
        self.assertEqual(status["reason"], "playback_ai_disabled")

    def test_concurrent_publish_and_read_remains_consistent(self) -> None:
        store = LatestAiPreviewStore()
        failures: list[str] = []

        def writer() -> None:
            for sequence in range(1, 500):
                store.publish(snapshot(sequence))

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            current = store.snapshot()
            if current is not None and store.image_for_sequence(current.sequence) is None:
                failures.append("metadata/image mismatch")
        thread.join()
        self.assertEqual(failures, [])


class PreviewEncoderTests(unittest.TestCase):
    def test_no_viewer_lease_skips_before_ownership_copy_and_expiry_stops_work(self) -> None:
        store = LatestAiPreviewStore()
        encoder = AiPreviewEncoder(store, maximum_fps=1000)
        gray = np.zeros((640, 640), dtype=np.uint8)
        self.assertFalse(encoder.submit(gray, capture(1)))
        self.assertEqual(encoder.status_metrics()["preview_skipped_without_viewer_total"], 1)
        self.assertFalse(encoder.status_metrics()["preview_viewer_lease_active"])

        encoder.renew_viewer_lease(0.02)
        self.assertTrue(encoder.submit(gray, capture(2)))
        self.assertTrue(encoder.status_metrics()["preview_viewer_lease_active"])
        time.sleep(0.03)
        self.assertFalse(encoder.submit(gray, capture(3)))
        self.assertFalse(encoder.status_metrics()["preview_viewer_lease_active"])

    def test_png_encoding_is_bounded_and_preserves_source_metadata(self) -> None:
        store = LatestAiPreviewStore()
        encoder = AiPreviewEncoder(store, maximum_fps=1000)
        encoder.start()
        try:
            gray = np.arange(640 * 640, dtype=np.uint32).reshape(640, 640).astype(np.uint8)
            encoder.renew_viewer_lease()
            encoder.submit(gray, capture(10, source="playback", epoch=4, config_id=3))
            deadline = time.monotonic() + 1.0
            while store.snapshot() is None and time.monotonic() < deadline:
                time.sleep(0.005)
            result = store.snapshot()
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual((result.source, result.playback_epoch, result.config_id), ("playback", 4, 3))
            decoded = np.asarray(Image.open(io.BytesIO(result.image)))
            np.testing.assert_array_equal(decoded, gray)
            self.assertLessEqual(encoder.status_metrics()["preview_queue_depth"], 1)
        finally:
            encoder.stop()

    def test_rate_limit_drops_without_copying_an_unbounded_history(self) -> None:
        store = LatestAiPreviewStore()
        encoder = AiPreviewEncoder(store, maximum_fps=4)
        gray = np.zeros((640, 640), dtype=np.uint8)
        encoder.renew_viewer_lease()
        self.assertTrue(encoder.submit(gray, capture(1)))
        self.assertFalse(encoder.submit(gray, capture(2)))
        metrics = encoder.status_metrics()
        self.assertEqual(metrics["preview_submitted_total"], 1)
        self.assertEqual(metrics["preview_dropped_total"], 1)
        self.assertLessEqual(metrics["preview_queue_depth"], 1)

    def test_clear_rejects_an_inflight_old_epoch_encode(self) -> None:
        store = LatestAiPreviewStore()
        encoder = AiPreviewEncoder(store, maximum_fps=1000)
        gray = np.zeros((640, 640), dtype=np.uint8)
        entered = threading.Event()
        release = threading.Event()
        original_save = Image.Image.save

        def delayed_save(image, target, *args, **kwargs):
            entered.set()
            release.wait(1.0)
            return original_save(image, target, *args, **kwargs)

        with patch.object(Image.Image, "save", delayed_save):
            encoder.start()
            try:
                encoder.renew_viewer_lease()
                encoder.submit(gray, capture(7, source="playback", epoch=3, config_id=2))
                self.assertTrue(entered.wait(1.0))
                encoder.clear("waiting")
                release.set()
                time.sleep(0.05)
                self.assertIsNone(store.snapshot())
            finally:
                release.set()
                encoder.stop()


class PreviewApiTests(unittest.TestCase):
    def test_status_and_image_headers_are_no_store_and_sequence_safe(self) -> None:
        current = snapshot(9)
        with patch.object(backend_main.service, "ai_preview_status", return_value=current.status()):
            status = asyncio.run(backend_main.ai_preview_status(viewer=True))
        self.assertEqual(status["sequence"], 9)
        with patch.object(backend_main.service, "ai_preview_image", return_value=current):
            response = asyncio.run(backend_main.ai_preview_image(9))
        self.assertEqual(response.headers["cache-control"], "no-store, no-cache, must-revalidate")
        self.assertEqual(response.headers["x-ai-preview-sequence"], "9")
        with patch.object(backend_main.service, "ai_preview_image", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(backend_main.ai_preview_image(8))
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
