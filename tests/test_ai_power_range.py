from __future__ import annotations

import asyncio
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException

import backend.main as backend_main
from backend.ai_stream.pipeline import AiStreamPipeline
from backend.ai_stream.power_profiles import dbm_to_gray8
from backend.ai_stream.power_range import (
    MIN_POWER_RANGE_DB,
    POWER_MAX_DBM,
    POWER_MIN_DBM,
    AiPowerRangeStore,
    validate_power_range,
)
from backend.analyzer.simulator import SimulatorSource
from backend.ai_detection_review import AiDetectionReviewSnapshot
from backend.api.service import AnalyzerService
from tools.yolo_detection import publish_review


class AiPowerRangeStoreTests(unittest.TestCase):
    def test_default_presets_custom_validation_and_derived_values(self) -> None:
        store = AiPowerRangeStore(None)
        default = store.current()
        self.assertEqual((default.preset, default.power_min_dbm, default.power_max_dbm), ("external_lna", -120.0, -20.0))
        custom = store.update(-95, -45)
        self.assertEqual((custom.mode, custom.preset, custom.range_db), ("custom", None, 50.0))
        self.assertAlmostEqual(custom.db_per_gray_level, 50 / 255)
        self.assertEqual(store.update_preset("normal").preset, "normal")
        self.assertEqual(store.update_preset("strong_signal").preset, "strong_signal")

    def test_invalid_ranges_are_rejected(self) -> None:
        invalid = [
            (-20, -20), (-10, -20), (-70, -61),
            (POWER_MIN_DBM - 1, -20), (-120, POWER_MAX_DBM + 1),
            (math.nan, -20), (-120, math.inf),
        ]
        for low, high in invalid:
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                validate_power_range(low, high)
        self.assertEqual(MIN_POWER_RANGE_DB, 10)

    def test_atomic_persistence_survives_reload_and_does_not_store_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai.json"
            store = AiPowerRangeStore(path)
            updated = store.update(-105, -35)
            self.assertEqual(updated.generation, 1)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["power_min_dbm"], -105)
            restored = AiPowerRangeStore(path).load()
            self.assertEqual((restored.power_min_dbm, restored.power_max_dbm, restored.generation), (-105, -35, 0))


class AiPowerRangeMappingTests(unittest.TestCase):
    def test_clipping_and_midpoint_mapping(self) -> None:
        values = np.full((640, 640), -75, dtype=np.float32)
        values[0, :5] = [-101, -100, -75, -50, -49]
        gray = dbm_to_gray8(values, -100, -50)
        self.assertEqual(gray[0, :5].tolist(), [0, 0, 128, 255, 255])

    def test_pipeline_swaps_mapping_without_rebuilding_components(self) -> None:
        with patch.dict("os.environ", {"AI_STREAM_ENABLED": "false"}):
            pipeline = AiStreamPipeline()
        accumulator = pipeline.accumulator
        publisher = pipeline.publisher
        pipeline.set_power_range(-100, -50, generation=7)
        self.assertIs(pipeline.accumulator, accumulator)
        self.assertIs(pipeline.publisher, publisher)
        status = pipeline.status()
        self.assertEqual((status["power_min_dbm"], status["power_max_dbm"], status["power_range_generation"]), (-100.0, -50.0, 7))

    def test_simulator_range_update_does_not_restart_or_reconfigure_acquisition(self) -> None:
        with patch.dict("os.environ", {"AI_STREAM_ENABLED": "false"}):
            source = SimulatorSource()
        source.connect()
        source.start()
        try:
            deadline = time.monotonic() + 1
            while source.get_status().configuration_generation == 0 and time.monotonic() < deadline:
                time.sleep(0.005)
            thread = source._thread
            generation = source.get_status().configuration_generation
            source.set_ai_power_range(-100, -50, 9)
            self.assertIs(source._thread, thread)
            self.assertTrue(source.get_status().acquisition_running)
            self.assertEqual(source.get_status().configuration_generation, generation)
        finally:
            source.disconnect()

    def test_yolo_review_forwards_optional_power_mapping_without_changing_framing(self) -> None:
        class Encoded:
            def __init__(self, value: bytes) -> None:
                self.value = value

            def tobytes(self) -> bytes:
                return self.value

        class Cv2:
            IMWRITE_JPEG_QUALITY = 1

            @staticmethod
            def imencode(_suffix, frame, _options):
                return True, Encoded(frame)

        class Publisher:
            parts = None

            def send_multipart(self, parts, flags=0):
                self.parts = parts

        publisher = Publisher()
        metadata = {
            "sequence": 2, "timestamp_ns": 3, "width": 640, "height": 640,
            "center_frequency_hz": 2.45e9, "start_frequency_hz": 2.4e9,
            "stop_frequency_hz": 2.5e9, "power_min_dbm": -100,
            "power_max_dbm": -50, "power_range_db": 50,
            "db_per_gray_level": 50 / 255, "power_range_generation": 6,
            "power_profile": "custom",
        }
        publish_review(Cv2(), publisher, metadata, b"raw", b"annotated", [], {}, {})
        self.assertIsNotNone(publisher.parts)
        self.assertEqual(len(publisher.parts), 3)
        forwarded = json.loads(publisher.parts[0])
        self.assertEqual((forwarded["power_min_dbm"], forwarded["power_max_dbm"], forwarded["power_range_generation"]), (-100, -50, 6))


class AiPowerRangeApiTests(unittest.TestCase):
    def test_get_and_put_delegate_to_authoritative_service(self) -> None:
        response = {
            "mode": "custom", "preset": None, "power_min_dbm": -100.0,
            "power_max_dbm": -50.0, "range_db": 50.0,
            "db_per_gray_level": 50 / 255, "generation": 3,
        }
        with patch.object(backend_main.service, "get_ai_power_range", return_value=response):
            self.assertEqual(asyncio.run(backend_main.ai_power_range()), response)
        with patch.object(backend_main.service, "set_ai_power_range", return_value=response) as setter:
            request = backend_main.AiPowerRangeRequest(power_min_dbm=-100, power_max_dbm=-50)
            self.assertEqual(asyncio.run(backend_main.update_ai_power_range(request)), response)
            setter.assert_awaited_once_with(-100.0, -50.0)

    def test_request_rejects_non_finite_values(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(Exception):
                backend_main.AiPowerRangeRequest(power_min_dbm=value, power_max_dbm=-20)

    def test_review_generation_rejects_stale_image_after_commit(self) -> None:
        def review(generation: int) -> AiDetectionReviewSnapshot:
            return AiDetectionReviewSnapshot(
                sequence=generation + 1, timestamp_ns=2, generated_at=3.0,
                received_at_ns=4, width=640, height=640,
                center_frequency_hz=2.45e9, start_frequency_hz=2.4e9,
                stop_frequency_hz=2.5e9, power_min_dbm=-120,
                power_max_dbm=-20, power_range_db=100,
                db_per_gray_level=100 / 255, power_range_generation=generation,
                content_type="image/jpeg", detections=[], label_freq_ranges_hz={},
                raw_image=b"raw", annotated_image=b"annotated",
            )

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "AI_DETECTION_SUB_ENABLED": "false",
            "AI_DETECTION_REVIEW_SUB_ENABLED": "false",
            "AI_DETECTION_DB_ENABLED": "false",
        }):
            service = AnalyzerService(
                "simulator", frequency_scan_config_path=None,
                recording_config_path=None, recording_root=directory,
                ai_power_range_config_path=None,
            )
            service._on_ai_review_snapshot(review(0))
            self.assertTrue(service.ai_review_status()["available"])
            asyncio.run(service.set_ai_power_range(-100, -50))
            playback_ai = service.playback.engine.source.ai_status()
            self.assertEqual((playback_ai["power_min_dbm"], playback_ai["power_max_dbm"]), (-100.0, -50.0))
            service._on_ai_review_snapshot(review(0))
            self.assertFalse(service.ai_review_status()["available"])
            matching = review(1)
            service._on_ai_review_snapshot(matching)
            self.assertEqual(service.ai_review_status()["sequence"], matching.sequence)


if __name__ == "__main__":
    unittest.main()
