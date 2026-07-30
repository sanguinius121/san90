from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from fastapi import HTTPException

import backend.main as backend_main
from backend.analyzer.san90 import San90Source
from backend.api.service import AnalyzerService
from backend.recording.adapter import build_san90_recording_packet
from backend.recording.config import (
    RECORDING_CONFIG_SCHEMA_VERSION,
    RecordingConfigStore,
    RecordingPreferences,
)
from backend.recording.models import (
    RecorderState,
    RecordingMode,
    StopReason,
    TimingFlags,
    TraceRecordFlags,
)
from backend.recording.reader import San90RtaReader


class NativeRecordingAdapterTests(unittest.TestCase):
    def test_native_packet_maps_dimensions_timing_flags_and_offsets_exactly(self) -> None:
        packet = build_san90_recording_packet(
            configuration_generation=9,
            first_sequence=120,
            trace_count=3,
            frame_width=4,
            center_frequency_hz=2.45e9,
            start_frequency_hz=2.4e9,
            stop_frequency_hz=2.5e9,
            rbw_hz=60_306.0,
            vbw_hz=6_030.6,
            sweep_time_s=0.0001,
            fft_size=8,
            reference_level_dbm=-10.0,
            hardware_scale_db_per_code=0.25,
            hardware_offset_dbm=-111.5,
            software_amplitude_offset_db=7.0,
            packet_acquisition_time_s=0.003,
            device_packet_timestamp_ns=123456,
            sdk_trace_timestamp_step_raw=16_384.0,
            if_overflow=True,
            if_overflow_latched=True,
            configuration_metadata={"verified": {"window": "blackman-nuttall"}},
            host_receipt_unix_ns=900,
            host_receipt_monotonic_ns=800,
        )
        self.assertEqual(packet.first_sequence, 120)
        self.assertEqual(packet.trace_count, 3)
        self.assertEqual(packet.configuration.frame_width, 4)
        self.assertEqual(packet.configuration.hardware_scale_db_per_code, 0.25)
        self.assertEqual(packet.configuration.hardware_offset_dbm, -111.5)
        self.assertEqual(packet.configuration.software_amplitude_offset_db, 7.0)
        self.assertEqual(packet.nominal_trace_period_ns, 1_000_000)
        self.assertEqual(packet.packet_acquisition_duration_ns, 3_000_000)
        self.assertEqual(packet.sdk_trace_timestamp_step_raw, 16_384.0)
        self.assertEqual(packet.host_receipt_unix_ns, 900)
        self.assertEqual(packet.host_receipt_monotonic_ns, 800)
        self.assertTrue(packet.timing_flags & TimingFlags.DEVICE_TIMESTAMP_PRESENT)
        self.assertTrue(packet.timing_flags & TimingFlags.PERIOD_FROM_PACKET_ACQUISITION)
        self.assertFalse(packet.timing_flags & TimingFlags.DEVICE_TIMESTAMP_HOST_EPOCH)
        self.assertTrue(packet.trace_flags & TraceRecordFlags.SDK_IF_OVERFLOW)
        self.assertTrue(packet.trace_flags & TraceRecordFlags.IF_OVERFLOW_LATCHED)

    def test_missing_device_time_is_not_invented_and_offer_exception_is_contained(self) -> None:
        packet = build_san90_recording_packet(
            configuration_generation=1,
            first_sequence=0,
            trace_count=2,
            frame_width=4,
            center_frequency_hz=1e9,
            start_frequency_hz=950e6,
            stop_frequency_hz=1.05e9,
            rbw_hz=60_306.0,
            vbw_hz=None,
            sweep_time_s=None,
            fft_size=8,
            reference_level_dbm=0,
            hardware_scale_db_per_code=0.5,
            hardware_offset_dbm=-120,
            software_amplitude_offset_db=0,
            packet_acquisition_time_s=float("nan"),
            device_packet_timestamp_ns=0,
            sdk_trace_timestamp_step_raw=16_384,
            if_overflow=False,
            if_overflow_latched=False,
            configuration_metadata={},
        )
        self.assertEqual(packet.device_packet_timestamp_ns, 0)
        self.assertEqual(packet.nominal_trace_period_ns, 0)
        self.assertEqual(packet.timing_flags, TimingFlags.NONE)
        source = San90Source.__new__(San90Source)
        source._recording_sink = Mock()
        source._recording_sink.offer_packet.side_effect = RuntimeError("contained")
        source._offer_recording_packet(np.zeros((2, 4), np.uint8), packet)
        source._recording_sink.offer_packet.assert_called_once()


class RecordingPersistenceTests(unittest.TestCase):
    def test_environment_selects_external_backend_owned_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "SAN90_Recordings"
            with patch.dict(
                os.environ,
                {"SAN90_RECORDING_ROOT": str(root)},
            ):
                store = RecordingConfigStore(path=None)
                self.assertEqual(store.recording_root, root)
                self.assertEqual(
                    store.resolve_output_directory(".", create=True),
                    root.resolve(),
                )
                self.assertTrue(root.is_dir())

    def test_missing_save_restart_malformed_and_runtime_not_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config" / "recording.json"
            store = RecordingConfigStore(path=path, recording_root=root / "recordings")
            defaults = store.load()
            self.assertEqual(defaults.mode, RecordingMode.FIXED)
            self.assertFalse(path.exists())
            expected = RecordingPreferences(
                RecordingMode.MANUAL,
                None,
                32 * 1024,
                0,
                "captures",
                "SAFE",
            )
            real_replace = os.replace
            with patch("backend.recording.config.os.replace", side_effect=real_replace) as replace_call:
                store.save(expected)
            replace_call.assert_called_once()
            document = json.loads(path.read_text())
            self.assertEqual(document["version"], RECORDING_CONFIG_SCHEMA_VERSION)
            for runtime_key in ("state", "session_uuid", "part_file_path", "stop_reason"):
                self.assertNotIn(runtime_key, document)
            restarted = RecordingConfigStore(path=path, recording_root=root / "recordings")
            self.assertEqual(restarted.load(), expected)
            path.write_text("{broken", encoding="utf-8")
            malformed = RecordingConfigStore(path=path, recording_root=root / "recordings")
            self.assertEqual(malformed.load().mode, RecordingMode.FIXED)
            self.assertIn("using defaults", malformed.load_warning or "")

    def test_unsafe_absolute_parent_and_symlink_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            recording_root = root / "recordings"
            recording_root.mkdir()
            (recording_root / "escape").symlink_to(outside, target_is_directory=True)
            store = RecordingConfigStore(path=None, recording_root=recording_root)
            for value in ("/tmp", "../escape", "escape"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    store.validate(
                        RecordingPreferences(
                            RecordingMode.MANUAL, None, 32 * 1024, 0, value, "SAFE"
                        )
                    ) if value != "escape" else store.resolve_output_directory(value, create=True)
            with self.assertRaises(ValueError):
                store.resolve_output_directory("escape/new", create=True)
            self.assertFalse((Path(outside) / "new").exists())

    def test_directory_listing_skips_symlinks_and_lists_nested_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory) / "recordings"
            store = RecordingConfigStore(path=None, recording_root=root)
            store.resolve_output_directory("field-tests/session-01", create=True)
            (root / "outside-link").symlink_to(outside, target_is_directory=True)
            self.assertEqual(
                store.list_output_directories(),
                [".", "field-tests", "field-tests/session-01"],
            )


class RecordingServiceAndApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = AnalyzerService(
            "simulator",
            frequency_scan_config_path=None,
            recording_config_path=root / "recording.json",
            recording_root=root / "recordings",
        )
        await self.service.start()

    async def asyncTearDown(self) -> None:
        await self.service.stop(disconnect=True)
        self.temp.cleanup()

    async def test_service_fixed_manual_status_duplicate_and_shutdown(self) -> None:
        self.service.configure_recording(
            RecordingPreferences(RecordingMode.FIXED, 0.06, 1 << 20, 0, ".", "FIXED")
        )
        started = await self.service.start_recording()
        self.assertEqual(started["state"], "recording")
        self.assertEqual(started["source"], "simulator")
        with self.assertRaises(Exception):
            await self.service.start_recording()
        self.assertTrue(self.service.recorder.wait(2))
        fixed = self.service.recording_status_payload()
        self.assertEqual(fixed["stop_reason"], "fixed_duration")
        self.assertTrue(Path(fixed["final_file_path"]).exists())
        self.assertEqual(San90RtaReader(fixed["final_file_path"]).validate().issues, [])

        self.service.configure_recording(
            RecordingPreferences(RecordingMode.MANUAL, None, 1 << 20, 0, ".", "MANUAL")
        )
        await self.service.start_recording()
        await self.service.stop_recording()
        await self.service.stop_recording()
        self.assertTrue(self.service.recorder.wait(2))
        manual = self.service.recording_status_payload()
        self.assertEqual(manual["stop_reason"], "user_stop")
        required = {
            "queue_bytes", "queue_items", "queue_fill_ratio", "queue_high_water_bytes",
            "enqueued_batches", "written_batches", "rejected_batches",
            "active_config_id", "active_configuration_generation",
            "available_disk_bytes", "total_disk_bytes",
        }
        self.assertTrue(required.issubset(manual))

    async def test_http_config_start_conflict_stop_and_status_routes(self) -> None:
        with patch.object(backend_main, "service", self.service):
            self.assertEqual((await backend_main.recording_config())["mode"], "fixed")
            created = await backend_main.create_recording_directory(
                backend_main.RecordingDirectoryRequest(path="field-tests/session-01")
            )
            self.assertEqual(created["created"], "field-tests/session-01")
            self.assertIn(
                "field-tests/session-01",
                (await backend_main.recording_directories())["directories"],
            )
            with self.assertRaises(HTTPException) as unsafe_directory:
                await backend_main.create_recording_directory(
                    backend_main.RecordingDirectoryRequest(path="../escape")
                )
            self.assertEqual(unsafe_directory.exception.status_code, 400)
            request = backend_main.RecordingConfigRequest(
                mode="manual",
                duration_s=None,
                file_size_limit_bytes=1 << 20,
                free_disk_reserve_bytes=0,
                output_directory=".",
                file_prefix="API",
            )
            self.assertEqual((await backend_main.update_recording_config(request))["mode"], "manual")
            started = await backend_main.start_recording()
            self.assertIsNotNone(started["part_file_path"])
            with self.assertRaises(HTTPException) as conflict:
                await backend_main.start_recording()
            self.assertEqual(conflict.exception.status_code, 409)
            mutation_request = request.model_copy(update={"file_prefix": "OTHER"})
            with self.assertRaises(HTTPException) as mutation:
                await backend_main.update_recording_config(mutation_request)
            self.assertEqual(mutation.exception.status_code, 409)
            await backend_main.stop_recording()
            await backend_main.stop_recording()
            self.assertEqual((await backend_main.recording_status())["source"], "simulator")
            registered = {route.path for route in backend_main.app.routes}
            self.assertTrue({
                "/api/analyzer/recording/config",
                "/api/analyzer/recording/directories",
                "/api/analyzer/recording/start",
                "/api/analyzer/recording/stop",
                "/api/analyzer/recording/status",
            }.issubset(registered))


if __name__ == "__main__":
    unittest.main()
