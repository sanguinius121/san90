from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.protocol import MESSAGE_SPECTRUM_TEMPORAL, MESSAGE_WATERFALL
from backend.api.service import AnalyzerService
from backend.playback.engine import PlaybackError
from backend.playback.models import PlaybackState
from backend.recording.models import RecordingConfig, RecordingMode
from backend.recording.recorder import RecordingConflictError
from tests.test_playback import write_fixture


class PlaybackServiceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_playback_is_sole_publication_source_and_simulator_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"AI_DETECTION_SUB_ENABLED": "0"}
        ):
            root = Path(directory)
            recording_root = root / "recordings"
            service = AnalyzerService(
                "simulator",
                frequency_scan_config_path=None,
                recording_config_path=None,
                recording_root=recording_root,
            )
            path = write_fixture(recording_root / "acceptance.san90rta", multi=True)
            await service.start()
            mailbox = service.register()
            try:
                entries = service.recordings_payload()["recordings"]
                self.assertEqual(len(entries), 1)
                recording_id = entries[0]["id"]
                simulator = service.source
                self.assertIsNotNone(simulator)
                before = simulator.get_status().sdk_frames_received
                ready = await service.open_playback(recording_id)
                self.assertEqual(ready["state"], PlaybackState.READY.value)
                self.assertEqual(service.status_payload()["source"], "playback")
                with self.assertRaises(RecordingConflictError):
                    await service.start_recording()
                configured = await service.configure_playback(auto_loop=False, run_ai=False)
                self.assertFalse(configured["auto_loop"])
                self.assertNotIn("speed", configured)
                await service.play_playback()
                seen: set[int] = set()
                deadline = asyncio.get_running_loop().time() + 1.5
                while asyncio.get_running_loop().time() < deadline:
                    if service.playback.engine.status().state == PlaybackState.COMPLETED:
                        break
                    try:
                        messages = await asyncio.wait_for(mailbox.take(), timeout=0.1)
                    except TimeoutError:
                        continue
                    seen.update(message[5] for message in messages)
                self.assertEqual(service.playback.engine.status().state, PlaybackState.COMPLETED)
                self.assertIn(MESSAGE_SPECTRUM_TEMPORAL, seen)
                self.assertIn(MESSAGE_WATERFALL, seen)
                self.assertGreater(simulator.get_status().sdk_frames_received, before)
                sought = await service.seek_playback(0.075)
                self.assertEqual(sought["state"], PlaybackState.PAUSED.value)
                self.assertEqual(sought["current_config_id"], 2)
                stepped = await service.step_playback("previous")
                self.assertEqual(stepped["state"], PlaybackState.PAUSED.value)
                await service.stop_playback()
                self.assertEqual(service.status_payload()["source"], "simulator")
                self.assertEqual(service.playback.engine.status().state, PlaybackState.IDLE)
            finally:
                service.unregister(mailbox)
                await service.stop(disconnect=True)

    async def test_active_recorder_blocks_playback_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"AI_DETECTION_SUB_ENABLED": "0"}
        ):
            root = Path(directory)
            recording_root = root / "recordings"
            service = AnalyzerService(
                "simulator",
                frequency_scan_config_path=None,
                recording_config_path=None,
                recording_root=recording_root,
            )
            write_fixture(recording_root / "blocked.san90rta")
            await service.start()
            try:
                recording_id = service.recordings_payload()["recordings"][0]["id"]
                service.recorder.start(
                    RecordingConfig(
                        RecordingMode.MANUAL,
                        recording_root,
                        "ACTIVE",
                        None,
                        1024 * 1024,
                        0,
                    ),
                    {"test": True},
                )
                with self.assertRaises(PlaybackError):
                    await service.open_playback(recording_id)
                service.recorder.stop()
            finally:
                await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
