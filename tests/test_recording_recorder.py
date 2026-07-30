from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from backend.recording.models import (
    GapReason,
    OfferResult,
    RecorderState,
    RecordingConfig,
    RecordingConfiguration,
    RecordingMode,
    RecordingPacket,
    StopReason,
)
from backend.recording.reader import San90RtaReader
from backend.recording.recorder import RecordingConflictError, San90RtaRecorder, configuration_fingerprint
from backend.recording.storage import RecordingStorage
from backend.recording.writer import San90RtaWriter


def config(*, generation: int = 1, width: int = 8, center: float = 2.45e9,
           scale: float = 0.5, amplitude: float = 0.0) -> RecordingConfiguration:
    span = 100e6
    return RecordingConfiguration(
        generation, center, center - span / 2, center + span / 2, span,
        60_306.0, 6_030.6, 0.001, 0.0, scale, -120.0, amplitude, width, width * 2,
        {"schema": "san90-config/1", "verified": {
            "window": "blackman-nuttall", "detector": "positive-peak",
        }},
    )


def packet(configuration: RecordingConfiguration, sequence: int, traces: int = 1) -> RecordingPacket:
    return RecordingPacket(
        configuration,
        sequence,
        traces,
        0,
        time.time_ns(),
        time.monotonic_ns(),
        1000,
        traces * 1000,
    )


def manual(directory: str, *, limit: int = 1 << 20) -> RecordingConfig:
    return RecordingConfig(
        RecordingMode.MANUAL,
        Path(directory),
        file_size_limit_bytes=limit,
        free_disk_reserve_bytes=0,
    )


class RecorderLifecycleTests(unittest.TestCase):
    def test_invalid_fixed_and_too_small_file_limit_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            with self.assertRaises(ValueError):
                recorder.start(
                    RecordingConfig(
                        RecordingMode.FIXED, Path(directory), duration_s=None,
                        file_size_limit_bytes=1 << 20, free_disk_reserve_bytes=0,
                    ),
                    {},
                )
            with self.assertRaises(ValueError):
                recorder.start(
                    RecordingConfig(
                        RecordingMode.MANUAL, Path(directory), file_size_limit_bytes=100,
                        free_disk_reserve_bytes=0,
                    ),
                    {},
                )
    def test_manual_lifecycle_duplicate_start_and_idempotent_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(writer_delay_s=0.02)
            self.assertEqual(recorder.start(manual(directory), {}).state, RecorderState.RECORDING)
            with self.assertRaises(RecordingConflictError):
                recorder.start(manual(directory), {})
            samples = np.arange(8, dtype=np.uint8)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 10)), OfferResult.ACCEPTED)
            samples[:] = 255
            first = recorder.stop(timeout=3)
            second = recorder.stop(timeout=0.1)
            self.assertEqual(first.state, RecorderState.COMPLETED)
            self.assertEqual(second.stop_reason, StopReason.USER_STOP)
            time.sleep(0.01)
            self.assertEqual(recorder.status().elapsed_s, second.elapsed_s)
            reader = San90RtaReader(first.final_file_path)
            report = reader.validate()
            self.assertEqual(report.issues, [])
            batch = next(reader.iter_trace_batches())
            self.assertEqual(batch.payload, bytes(range(8)))

    def test_fixed_duration_stops_without_hot_path_timer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            recorder.start(
                RecordingConfig(
                    RecordingMode.FIXED, Path(directory), duration_s=0.05,
                    file_size_limit_bytes=1 << 20, free_disk_reserve_bytes=0,
                ),
                {},
            )
            self.assertTrue(recorder.wait(2))
            status = recorder.status()
            self.assertEqual(status.state, RecorderState.COMPLETED)
            self.assertEqual(status.stop_reason, StopReason.FIXED_DURATION)

    def test_disconnect_and_shutdown_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(writer_delay_s=0.02)
            recorder.start(manual(directory), {})
            recorder.stop(StopReason.USER_STOP)
            recorder.source_disconnected()
            recorder.shutdown(timeout=3)
            self.assertEqual(recorder.status().stop_reason, StopReason.DEVICE_DISCONNECT)

    def test_config_fingerprint_uses_disk_precision(self) -> None:
        base = config()
        self.assertEqual(configuration_fingerprint(base), configuration_fingerprint(replace(base)))
        self.assertNotEqual(configuration_fingerprint(base), configuration_fingerprint(replace(base, hardware_scale_db_per_code=0.6)))
        self.assertNotEqual(configuration_fingerprint(base), configuration_fingerprint(replace(base, software_amplitude_offset_db=1.0)))


class RecorderQueueAndConfigTests(unittest.TestCase):
    def test_generation_mapping_and_frame_width_changes_create_configs_in_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            recorder.start(manual(directory), {})
            variants = (
                config(),
                config(),  # identical: no duplicate CONFIG
                config(generation=2, center=5.75e9),
                config(generation=2, center=5.75e9, scale=0.6),
                config(generation=3, width=4, center=900e6, amplitude=2.0),
            )
            sequence = 0
            for item in variants:
                payload = np.arange(item.frame_width, dtype=np.uint8)
                self.assertEqual(recorder.offer_packet(payload, packet(item, sequence)), OfferResult.ACCEPTED)
                sequence += 1
            status = recorder.stop(timeout=3)
            report = San90RtaReader(status.final_file_path).validate()
            self.assertEqual(report.issues, [])
            self.assertEqual(report.config_record_count, 4)
            self.assertEqual(report.trace_batch_count, 5)
            self.assertEqual(len({entry.configuration_generation for entry in report.configurations}), 3)

    def test_transient_overflow_coalesces_gap_before_next_trace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(
                max_queue_bytes=8, max_queue_items=4, writer_delay_s=0.08,
                overrun_duration_ns=10**12, overrun_rejected_bytes=10**9,
            )
            recorder.start(manual(directory), {})
            samples = np.arange(8, dtype=np.uint8)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 0)), OfferResult.ACCEPTED)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 1)), OfferResult.REJECTED_QUEUE_FULL)
            deadline = time.monotonic() + 1
            while recorder.status().queue_bytes and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 2)), OfferResult.ACCEPTED)
            status = recorder.stop(timeout=3)
            report = San90RtaReader(status.final_file_path).validate()
            self.assertEqual(report.issues, [])
            self.assertEqual(report.gap_count, 1)
            self.assertEqual(report.lost_trace_count, 1)
            records = list(San90RtaReader(status.final_file_path).iter_records())
            gap_index = next(index for index, record in enumerate(records) if record.__class__.__name__ == "GapRecord")
            second_trace_index = [index for index, record in enumerate(records) if record.__class__.__name__ == "TraceBatchRecord"][1]
            self.assertLess(gap_index, second_trace_index)

    def test_sustained_overrun_stops_out_of_band_when_queue_full(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(
                max_queue_bytes=8, max_queue_items=1, writer_delay_s=0.1,
                overrun_duration_ns=10**12, overrun_rejected_bytes=8,
            )
            recorder.start(manual(directory), {})
            samples = np.arange(8, dtype=np.uint8)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 0)), OfferResult.ACCEPTED)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 1)), OfferResult.REJECTED_QUEUE_FULL)
            self.assertTrue(recorder.wait(3))
            status = recorder.status()
            self.assertEqual(status.stop_reason, StopReason.WRITER_OVERRUN)
            self.assertEqual(status.state, RecorderState.COMPLETED)
            report = San90RtaReader(status.final_file_path).validate()
            self.assertEqual(report.issues, [])
            self.assertEqual(report.gap_count, 1)

    def test_item_and_byte_limits_are_independent_and_offer_is_fast(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(max_queue_bytes=8, max_queue_items=1, writer_delay_s=0.2)
            recorder.start(manual(directory), {})
            samples = np.arange(8, dtype=np.uint8)
            self.assertEqual(recorder.offer_packet(samples, packet(config(), 0)), OfferResult.ACCEPTED)
            started = time.perf_counter()
            result = recorder.offer_packet(samples, packet(config(), 1))
            self.assertLess(time.perf_counter() - started, 0.02)
            self.assertEqual(result, OfferResult.REJECTED_QUEUE_FULL)
            status = recorder.stop(timeout=3)
            self.assertEqual(status.queue_high_water_bytes, 8)
            self.assertEqual(status.queue_high_water_items, 1)

    def test_rejected_packet_is_not_copied(self) -> None:
        class CopyTrap(np.ndarray):
            def tobytes(self, order="C"):
                raise AssertionError("rejected payload must not be copied")

        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(max_queue_bytes=8, max_queue_items=1, writer_delay_s=0.2)
            recorder.start(manual(directory), {})
            recorder.offer_packet(np.arange(8, dtype=np.uint8), packet(config(), 0))
            trapped = np.arange(8, dtype=np.uint8).view(CopyTrap)
            self.assertEqual(
                recorder.offer_packet(trapped, packet(config(), 1)),
                OfferResult.REJECTED_QUEUE_FULL,
            )
            recorder.stop(timeout=3)

    def test_reconfiguration_pause_is_explicit_and_zero_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder()
            recorder.start(manual(directory), {})
            samples = np.arange(8, dtype=np.uint8)
            recorder.offer_packet(samples, packet(config(), 0))
            now = time.monotonic_ns()
            self.assertTrue(recorder.note_reconfiguration_pause(
                start_monotonic_ns=now, end_monotonic_ns=now + 100, next_sequence=1
            ))
            recorder.offer_packet(samples, packet(config(generation=2, center=900e6), 1))
            status = recorder.stop(timeout=3)
            report = San90RtaReader(status.final_file_path).validate()
            self.assertEqual(report.issues, [])
            gaps = [record for record in San90RtaReader(status.final_file_path).iter_records()
                    if record.__class__.__name__ == "GapRecord"]
            self.assertEqual(gaps[0].reason_code, GapReason.RECONFIGURATION_PAUSE)
            self.assertEqual(gaps[0].estimated_lost_trace_count, 0)

    def test_file_size_limit_stops_before_limit_and_preserves_finalize_reserve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            limit = 16 * 1024
            recorder = San90RtaRecorder()
            recorder.start(manual(directory, limit=limit), {})
            samples = np.arange(12 * 1024, dtype=np.uint8)
            result = recorder.offer_packet(samples, packet(config(width=12 * 1024), 0))
            self.assertEqual(result, OfferResult.REJECTED_LIMIT)
            self.assertTrue(recorder.wait(3))
            status = recorder.status()
            self.assertEqual(status.stop_reason, StopReason.FILE_SIZE_LIMIT)
            self.assertLessEqual(Path(status.final_file_path).stat().st_size, limit)
            self.assertEqual(San90RtaReader(status.final_file_path).validate().issues, [])

    def test_low_disk_stops_cleanly_without_deleting_data(self) -> None:
        class LowAfterOpenStorage(RecordingStorage):
            def ensure_free_reserve(self, reserve_bytes: int) -> int:
                return reserve_bytes + 1

            def free_bytes(self) -> int:
                return 0

        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(storage_factory=LowAfterOpenStorage)
            recorder.start(
                RecordingConfig(
                    RecordingMode.MANUAL, Path(directory), file_size_limit_bytes=1 << 20,
                    free_disk_reserve_bytes=1,
                ),
                {},
            )
            self.assertEqual(
                recorder.offer_packet(np.arange(8, dtype=np.uint8), packet(config(), 0)),
                OfferResult.ACCEPTED,
            )
            self.assertTrue(recorder.wait(3))
            status = recorder.status()
            self.assertEqual(status.stop_reason, StopReason.LOW_DISK)
            self.assertEqual(status.state, RecorderState.COMPLETED)
            self.assertTrue(Path(status.final_file_path).exists())
            self.assertEqual(San90RtaReader(status.final_file_path).validate().issues, [])

    def test_writer_error_fails_but_leaves_recoverable_part(self) -> None:
        class FailingTraceWriter(San90RtaWriter):
            def write_trace_batch(self, **kwargs):
                raise OSError("injected writer failure")

        def writer_factory(storage, **kwargs):
            return FailingTraceWriter.open_session(storage, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            recorder = San90RtaRecorder(writer_factory=writer_factory)
            recorder.start(manual(directory), {})
            recorder.offer_packet(np.arange(8, dtype=np.uint8), packet(config(), 0))
            self.assertTrue(recorder.wait(3))
            status = recorder.status()
            self.assertEqual(status.state, RecorderState.FAILED)
            self.assertEqual(status.stop_reason, StopReason.WRITER_ERROR)
            self.assertIsNone(status.final_file_path)
            self.assertTrue(Path(status.part_file_path).exists())
            self.assertTrue(San90RtaReader(status.part_file_path).validate().recoverable)


if __name__ == "__main__":
    unittest.main()
