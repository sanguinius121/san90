from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from pydantic import ValidationError

import backend.main as backend_main
from backend.playback.engine import PlaybackEngine, PlaybackError
from backend.playback.index import build_playback_index
from backend.playback.models import PlaybackState
from backend.playback.source import PlaybackSource
from backend.playback.storage import RecordingCatalog
from backend.recording.format import RecordingFormatError
from backend.recording.models import GapFlags, GapReason
from tests.recording_fixtures import CREATED_NS, START_MONOTONIC_NS, FixtureBuilder


def write_fixture(path: Path, *, multi: bool = False, gap: bool = False) -> Path:
    builder = FixtureBuilder()
    builder.add_session()
    builder.add_config()
    builder.add_trace(host_monotonic_ns=START_MONOTONIC_NS + 10_000_000)
    if gap:
        builder.add_gap(
            expected_sequence=102,
            next_sequence=102,
            lost=0,
            reason=GapReason.RECONFIGURATION_PAUSE,
            flags=GapFlags.PAUSE_WITHOUT_OBSERVED_LOSS,
            start_monotonic_ns=START_MONOTONIC_NS + 20_000_000,
            end_monotonic_ns=START_MONOTONIC_NS + 70_000_000,
        )
    if multi:
        builder.add_trace(
            first_sequence=102,
            host_monotonic_ns=START_MONOTONIC_NS + 35_000_000,
        )
        builder.add_config(
            config_id=2,
            generation=8,
            first_sequence=104,
            frame_width=8,
            start_hz=890_000_000,
            stop_hz=910_000_000,
            amplitude_offset_db=-2.0,
        )
        builder.add_trace(
            config_id=2,
            generation=8,
            first_sequence=104,
            trace_count=1,
            frame_width=8,
            payload=bytes(range(8)),
            host_monotonic_ns=START_MONOTONIC_NS + 80_000_000,
        )
    path.write_bytes(builder.finish())
    return path


class PlaybackCatalogAndIndexTests(unittest.TestCase):
    def test_catalog_lists_only_final_files_and_uses_opaque_safe_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "field"
            nested.mkdir()
            valid = write_fixture(nested / "clean.san90rta")
            (root / "active.san90rta.part").write_bytes(valid.read_bytes())
            (root / "bad.san90rta").write_bytes(b"bad")
            catalog = RecordingCatalog(root)
            entries = catalog.list()
            self.assertEqual({entry.filename for entry in entries}, {"field/clean.san90rta", "bad.san90rta"})
            clean = next(entry for entry in entries if entry.playable)
            self.assertEqual(len(clean.id), 32)
            self.assertNotIn(str(root), repr(clean))
            self.assertEqual(catalog.resolve(clean.id), valid)
            with self.assertRaises(FileNotFoundError):
                catalog.resolve("../clean.san90rta")
            corrupt = next(entry for entry in entries if not entry.playable)
            self.assertFalse(corrupt.complete)

    def test_index_single_and_multiple_configs_without_trace_payload_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "multi.san90rta", multi=True)
            index = build_playback_index(path)
            self.assertEqual(len(index.configurations), 2)
            self.assertEqual([batch.frame_width for batch in index.batches], [4, 4, 8])
            self.assertFalse(hasattr(index.batches[0], "payload"))
            self.assertAlmostEqual(index.batches[2].cumulative_time_s, 0.07, places=6)
            self.assertEqual(index.end.trace_count, 5)

    def test_part_missing_config_and_corrupt_header_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = write_fixture(root / "valid.san90rta")
            (root / "copy.san90rta.part").write_bytes(valid.read_bytes())
            with self.assertRaises(RecordingFormatError):
                build_playback_index(root / "copy.san90rta.part")
            corrupted = bytearray(valid.read_bytes())
            corrupted[100] ^= 0x20
            (root / "corrupt.san90rta").write_bytes(corrupted)
            with self.assertRaises(RecordingFormatError):
                build_playback_index(root / "corrupt.san90rta")
            truncated = valid.read_bytes()[:-20]
            (root / "truncated.san90rta").write_bytes(truncated)
            with self.assertRaises(RecordingFormatError) as caught:
                build_playback_index(root / "truncated.san90rta")
            self.assertIsNotNone(caught.exception.offset)


class PlaybackSourceTests(unittest.TestCase):
    def test_mapping_applies_software_offset_exactly_once_and_config_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = build_playback_index(write_fixture(Path(directory) / "multi.san90rta", multi=True))
            source = PlaybackSource()
            source.connect()
            source.start()
            first = index.batches[0]
            source.activate_config(index.configurations[first.config_id])
            source.consume_batch(first, bytes(range(1, 9)))
            source.flush()
            frame = source.read_spectrum_temporal()
            self.assertIsNotNone(frame)
            assert frame is not None
            expected = np.arange(5, 9, dtype=np.float32) * 0.5 - 100.0 + 1.25
            np.testing.assert_allclose(frame.latest_trace_float32, expected)
            second = index.batches[2]
            source.activate_config(index.configurations[second.config_id])
            self.assertEqual(source.get_settings_state().actual.point_count, 8)
            self.assertEqual(source.activation_count, 2)
            source.activate_config(index.configurations[second.config_id])
            self.assertEqual(source.activation_count, 2)

    def test_calibration_only_config_change_preserves_waterfall_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = build_playback_index(write_fixture(Path(directory) / "calibration.san90rta"))
            source = PlaybackSource()
            source.connect()
            source.start()
            first = index.configurations[1]
            source.activate_config(first)
            initial_generation = source.get_status().configuration_generation
            initial_waterfall = source._waterfall

            calibrated = replace(
                first,
                config_id=2,
                hardware_offset_dbm=first.hardware_offset_dbm - 0.075,
            )
            source.activate_config(calibrated)

            self.assertEqual(source.activation_count, 2)
            self.assertEqual(source.get_status().configuration_generation, initial_generation)
            self.assertIs(source._waterfall, initial_waterfall)
            self.assertAlmostEqual(
                source.get_settings_state().actual.offset_to_dbm or 0.0,
                calibrated.hardware_offset_dbm,
            )

            retuned = replace(
                calibrated,
                config_id=3,
                center_frequency_hz=calibrated.center_frequency_hz + 1_000_000,
                start_frequency_hz=calibrated.start_frequency_hz + 1_000_000,
                stop_frequency_hz=calibrated.stop_frequency_hz + 1_000_000,
            )
            source.activate_config(retuned)
            self.assertEqual(
                source.get_status().configuration_generation,
                initial_generation + 1,
            )


class PlaybackEngineTests(unittest.TestCase):
    def test_settings_contract_has_no_speed_field(self) -> None:
        request = backend_main.PlaybackSettingsRequest(auto_loop=True, run_ai=False)
        self.assertEqual(request.model_dump(), {"auto_loop": True, "run_ai": False})
        with self.assertRaises(ValidationError):
            backend_main.PlaybackSettingsRequest.model_validate(
                {"auto_loop": True, "run_ai": False, "speed": 2.0}
            )

    def test_open_play_pause_resume_complete_and_idempotent_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "timed.san90rta", multi=True)
            engine = PlaybackEngine()
            ready = engine.open(path, recording_id="a" * 32, filename=path.name, previous_source="simulator")
            self.assertEqual(ready.state, PlaybackState.READY)
            self.assertEqual(engine.play().state, PlaybackState.PLAYING)
            time.sleep(0.025)
            paused = engine.pause()
            self.assertEqual(paused.state, PlaybackState.PAUSED)
            position = paused.position_s
            time.sleep(0.03)
            self.assertAlmostEqual(engine.status().position_s, position, places=3)
            engine.play()
            deadline = time.monotonic() + 1.5
            while engine.status().state == PlaybackState.PLAYING and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(engine.status().state, PlaybackState.COMPLETED)
            self.assertEqual(engine.stop().state, PlaybackState.IDLE)
            self.assertEqual(engine.stop().state, PlaybackState.IDLE)

    def test_invalid_states_and_payload_crc_failure(self) -> None:
        engine = PlaybackEngine()
        with self.assertRaises(PlaybackError):
            engine.play()
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "crc.san90rta")
            engine.open(path, recording_id="b" * 32, filename=path.name, previous_source="hardware")
            index = build_playback_index(path)
            data = bytearray(path.read_bytes())
            data[index.batches[0].payload_offset] ^= 0xFF
            path.write_bytes(data)
            engine.play()
            deadline = time.monotonic() + 1.5
            while engine.status().state == PlaybackState.PLAYING and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(engine.status().state, PlaybackState.FAILED)
            self.assertIn("CRC32C", engine.status().last_error or "")
            engine.stop()

    def test_reconfiguration_gap_is_not_counted_as_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "gap.san90rta", multi=True, gap=True)
            engine = PlaybackEngine()
            engine.open(path, recording_id="c" * 32, filename=path.name, previous_source="hardware")
            engine.play()
            deadline = time.monotonic() + 1.5
            while engine.status().state == PlaybackState.PLAYING and time.monotonic() < deadline:
                time.sleep(0.005)
            status = engine.status()
            self.assertEqual(status.gaps_passed, 1)
            self.assertEqual(status.reconfiguration_pauses_passed, 1)
            self.assertEqual(status.lost_traces_passed, 0)
            engine.stop()

    def test_seek_resets_epoch_publishes_target_and_ends_paused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "seek.san90rta", multi=True)
            source = PlaybackSource()
            engine = PlaybackEngine(source)
            opened = engine.open(path, recording_id="d" * 32, filename=path.name, previous_source="simulator")
            sought = engine.seek(0.075)
            self.assertEqual(sought.state, PlaybackState.PAUSED)
            self.assertGreater(sought.playback_epoch, opened.playback_epoch)
            self.assertEqual(sought.current_config_id, 2)
            self.assertEqual(sought.current_trace_index, 0)
            self.assertEqual(sought.center_frequency_hz, 900_000_000.0)
            self.assertIsNotNone(source.read_spectrum_temporal())
            engine.stop()

    def test_step_within_and_across_batches_and_config_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "step.san90rta", multi=True)
            engine = PlaybackEngine()
            opened = engine.open(path, recording_id="e" * 32, filename=path.name, previous_source="simulator")
            first = engine.step("next")
            self.assertEqual(first.current_sequence, 100)
            epoch = first.playback_epoch
            second = engine.step("next")
            self.assertEqual(second.current_sequence, 101)
            across_batch = engine.step("next")
            self.assertEqual(across_batch.current_sequence, 102)
            previous = engine.step("previous")
            self.assertEqual(previous.current_sequence, 101)
            engine.step("next")
            engine.step("next")
            config_two = engine.step("next")
            self.assertEqual(config_two.current_config_id, 2)
            self.assertEqual(config_two.current_sequence, 104)
            self.assertGreater(config_two.playback_epoch, epoch)
            at_end = engine.step("next")
            self.assertEqual(at_end.current_sequence, 104)
            engine.stop()

    def test_auto_loop_reuses_open_descriptor_and_stop_interrupts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_fixture(Path(directory) / "loop.san90rta")
            engine = PlaybackEngine()
            opened = engine.open(path, recording_id="f" * 32, filename=path.name, previous_source="simulator")
            descriptor = engine._fd
            configured = engine.configure(auto_loop=True, run_ai=False)
            self.assertTrue(configured.auto_loop)
            self.assertFalse(hasattr(configured, "speed"))
            engine.play()
            deadline = time.monotonic() + 1.5
            while engine.status().loop_count < 1 and time.monotonic() < deadline:
                time.sleep(0.005)
            looped = engine.status()
            self.assertGreaterEqual(looped.loop_count, 1)
            self.assertGreater(looped.playback_epoch, opened.playback_epoch)
            self.assertEqual(engine._fd, descriptor)
            self.assertEqual(engine.stop().state, PlaybackState.IDLE)

    def test_ai_epoch_and_config_correlation_rejects_stale_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = build_playback_index(write_fixture(Path(directory) / "ai.san90rta", multi=True))
            source = PlaybackSource()
            source.connect()
            source.start()
            source.reset_timeline(3, index.configurations[1])
            with source._lock:
                source._run_ai = True
                source._ai_outstanding[123] = (3, 1)
            accepted = source.accept_ai_result({"sequence": 123, "detections": []})
            self.assertIsNotNone(accepted)
            assert accepted is not None
            self.assertEqual(accepted["playback_epoch"], 3)
            with source._lock:
                source._ai_outstanding[124] = (3, 1)
            source.reset_timeline(4, index.configurations[1])
            self.assertIsNone(source.accept_ai_result({"sequence": 124, "detections": []}))
            with source._lock:
                source._ai_outstanding[125] = (4, 1)
            source.activate_config(index.configurations[2])
            self.assertIsNone(source.accept_ai_result({"sequence": 125, "detections": []}))
            source.disconnect()


if __name__ == "__main__":
    unittest.main()
