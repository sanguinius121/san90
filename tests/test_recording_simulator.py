from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from backend.analyzer.simulator import SimulatorSource
from backend.recording.models import RecorderState, RecordingConfig, RecordingMode, StopReason
from backend.recording.reader import San90RtaReader
from backend.recording.recorder import San90RtaRecorder


class RecordingSimulatorTests(unittest.TestCase):
    def test_simulator_fixed_and_configuration_change_preserve_realtime_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            recorder.start(
                RecordingConfig(
                    RecordingMode.MANUAL,
                    Path(directory),
                    file_size_limit_bytes=1 << 20,
                    free_disk_reserve_bytes=0,
                ),
                {"device": {"model": "Spectrum simulator", "uid": "SIM-0001"}},
            )
            simulator = SimulatorSource(point_count=32, frame_rate_hz=120, seed=3)
            simulator.set_recording_sink(recorder)
            simulator.connect()
            simulator.start()
            deadline = time.monotonic() + 1
            frame = None
            while frame is None and time.monotonic() < deadline:
                frame = simulator.read_frame()
                time.sleep(0.005)
            self.assertIsNotNone(frame)
            settings = simulator.get_settings()
            pause_start = time.monotonic_ns()
            simulator.apply_settings(replace(settings, center_frequency_hz=900e6))
            pause_end = time.monotonic_ns()
            recorder.note_reconfiguration_pause(
                start_monotonic_ns=pause_start,
                end_monotonic_ns=pause_end,
                next_sequence=simulator.get_status().sdk_frames_received,
            )
            time.sleep(0.08)
            self.assertGreater(simulator.get_status().sdk_frames_received, 1)
            self.assertIsNotNone(simulator.read_frame())
            simulator.set_recording_sink(None)
            simulator.disconnect()
            status = recorder.stop(timeout=3)
            self.assertEqual(status.state, RecorderState.COMPLETED)
            report = San90RtaReader(status.final_file_path).validate()
            self.assertEqual(report.issues, [])
            self.assertGreaterEqual(report.config_record_count, 2)
            self.assertGreater(report.trace_batch_count, 1)
            self.assertEqual(report.gap_count, 1)

    def test_simulator_disconnect_stops_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            recorder.start(
                RecordingConfig(
                    RecordingMode.MANUAL, Path(directory),
                    file_size_limit_bytes=1 << 20, free_disk_reserve_bytes=0,
                ),
                {},
            )
            simulator = SimulatorSource(point_count=32, frame_rate_hz=120, seed=4)
            simulator.set_recording_sink(recorder)
            simulator.connect()
            simulator.start()
            time.sleep(0.05)
            simulator.disconnect()
            self.assertTrue(recorder.wait(3))
            self.assertEqual(recorder.status().stop_reason, StopReason.DEVICE_DISCONNECT)

    def test_simulator_writer_delay_exercises_transient_gap_and_sustained_overrun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transient = San90RtaRecorder(
                max_queue_bytes=32,
                max_queue_items=2,
                writer_delay_s=0.04,
                overrun_duration_ns=10**12,
                overrun_rejected_bytes=10**9,
            )
            transient.start(
                RecordingConfig(
                    RecordingMode.MANUAL, Path(directory),
                    file_prefix="transient", file_size_limit_bytes=1 << 20,
                    free_disk_reserve_bytes=0,
                ),
                {},
            )
            simulator = SimulatorSource(point_count=32, frame_rate_hz=120, seed=5)
            simulator.set_recording_sink(transient)
            simulator.connect()
            simulator.start()
            time.sleep(0.20)
            simulator.set_recording_sink(None)
            simulator.disconnect()
            transient_status = transient.stop(timeout=3)
            transient_report = San90RtaReader(transient_status.final_file_path).validate()
            self.assertEqual(transient_report.issues, [])
            self.assertGreater(transient_report.gap_count, 0)

        with tempfile.TemporaryDirectory() as directory:
            sustained = San90RtaRecorder(
                max_queue_bytes=32,
                max_queue_items=1,
                writer_delay_s=0.10,
                overrun_duration_ns=10**12,
                overrun_rejected_bytes=32,
            )
            sustained.start(
                RecordingConfig(
                    RecordingMode.MANUAL, Path(directory),
                    file_prefix="sustained", file_size_limit_bytes=1 << 20,
                    free_disk_reserve_bytes=0,
                ),
                {},
            )
            simulator = SimulatorSource(point_count=32, frame_rate_hz=120, seed=6)
            simulator.set_recording_sink(sustained)
            simulator.connect()
            simulator.start()
            self.assertTrue(sustained.wait(3))
            frames_at_stop = simulator.get_status().sdk_frames_received
            time.sleep(0.04)
            self.assertGreater(simulator.get_status().sdk_frames_received, frames_at_stop)
            simulator.set_recording_sink(None)
            simulator.disconnect()
            self.assertEqual(sustained.status().stop_reason, StopReason.WRITER_OVERRUN)


if __name__ == "__main__":
    unittest.main()
