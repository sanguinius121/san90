from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from backend.recording.models import (
    RecordingConfiguration,
    StopReason,
    TimingFlags,
    TraceRecordFlags,
)
from backend.recording.reader import San90RtaReader
from backend.recording.storage import RecordingStorage
from backend.recording.writer import RecordingWriterError, San90RtaWriter


def configuration(*, generation: int = 1, width: int = 4) -> RecordingConfiguration:
    return RecordingConfiguration(
        generation,
        2.45e9,
        2.4e9,
        2.5e9,
        1e8,
        60_306.0,
        6_030.6,
        0.001,
        0.0,
        0.5,
        -120.0,
        1.0,
        width,
        width * 2,
        {"schema": "san90-config/1", "verified": {"window": "blackman-nuttall"}},
    )


def write_minimal(writer: San90RtaWriter) -> None:
    writer.write_session_metadata({"schema": "san90-session-metadata/1"})
    writer.write_config(
        config_id=1,
        configuration=configuration(),
        effective_first_sequence=10,
        effective_host_unix_ns=100,
        effective_host_monotonic_ns=200,
    )
    writer.write_trace_batch(
        config_id=1,
        configuration_generation=1,
        first_sequence=10,
        trace_count=2,
        frame_width=4,
        device_packet_timestamp_ns=0,
        host_receipt_unix_ns=101,
        host_receipt_monotonic_ns=201,
        nominal_trace_period_ns=1,
        packet_acquisition_duration_ns=2,
        sdk_trace_timestamp_step_raw=0.0,
        timing_flags=TimingFlags.NONE,
        trace_flags=TraceRecordFlags.NONE,
        payload=b"\x01\x02\x03\x04\x05\x06\x07\x08",
    )


class RecordingWriterTests(unittest.TestCase):
    def test_storage_rejects_unsafe_prefix_and_exclusive_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = RecordingStorage(directory)
            with self.assertRaises(ValueError):
                storage.open_session(prefix="../escape", session_uuid=uuid4(), creation_unix_ns=1)
            identifier = UUID("12345678-1234-5678-1234-567812345678")
            first = storage.open_session(prefix="safe", session_uuid=identifier, creation_unix_ns=1)
            with self.assertRaises(OSError):
                storage.open_session(prefix="safe", session_uuid=identifier, creation_unix_ns=1)
            os.close(first.fd)

    def test_sequential_writer_finalizes_and_reader_validates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = San90RtaWriter.open_session(RecordingStorage(directory), file_prefix="writer")
            self.assertEqual(writer.part_path.stat().st_mode & 0o777, 0o600)
            write_minimal(writer)
            final_path = writer.finalize(stop_reason=StopReason.USER_STOP)
            self.assertFalse(writer.part_path.exists())
            self.assertTrue(final_path.exists())
            report = San90RtaReader(final_path).validate()
            self.assertEqual(report.issues, [])
            self.assertTrue(report.clean_finalization)
            self.assertEqual(report.trace_count, 2)
            indexes = [record.prefix.record_index for record in San90RtaReader(final_path).iter_records()]
            self.assertEqual(indexes, list(range(1, len(indexes) + 1)))

    def test_partial_os_writes_are_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            def short_write(fd: int, data: bytes) -> int:
                return os.write(fd, data[: max(1, min(7, len(data)))])

            writer = San90RtaWriter.open_session(
                RecordingStorage(directory), file_prefix="short", write_func=short_write
            )
            write_minimal(writer)
            final_path = writer.finalize(stop_reason=StopReason.USER_STOP)
            self.assertEqual(San90RtaReader(final_path).validate().issues, [])

    def test_unknown_config_and_mismatch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = San90RtaWriter.open_session(RecordingStorage(directory), file_prefix="reject")
            writer.write_session_metadata({})
            kwargs = dict(
                config_id=9, configuration_generation=1, first_sequence=0, trace_count=1,
                frame_width=4, device_packet_timestamp_ns=0, host_receipt_unix_ns=0,
                host_receipt_monotonic_ns=0, nominal_trace_period_ns=0,
                packet_acquisition_duration_ns=0, sdk_trace_timestamp_step_raw=0.0,
                timing_flags=TimingFlags.NONE, trace_flags=TraceRecordFlags.NONE, payload=b"1234",
            )
            with self.assertRaises(ValueError):
                writer.write_trace_batch(**kwargs)
            writer.abort()
            self.assertTrue(writer.part_path.exists())

    def test_existing_final_file_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = San90RtaWriter.open_session(RecordingStorage(directory), file_prefix="collision")
            write_minimal(writer)
            writer.final_path.write_bytes(b"existing")
            with self.assertRaises(RecordingWriterError):
                writer.finalize(stop_reason=StopReason.USER_STOP)
            self.assertEqual(writer.final_path.read_bytes(), b"existing")
            self.assertTrue(writer.part_path.exists())

    def test_fsync_failure_retains_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            writer = San90RtaWriter.open_session(RecordingStorage(directory), file_prefix="fsync")
            write_minimal(writer)
            with patch("backend.recording.writer.os.fsync", side_effect=OSError(errno.EIO, "injected")):
                with self.assertRaises(RecordingWriterError):
                    writer.finalize(stop_reason=StopReason.USER_STOP)
            self.assertTrue(writer.part_path.exists())
            self.assertTrue(San90RtaReader(writer.part_path).validate().complete)

    def test_failed_partial_record_retains_recoverable_part(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls = 0

            def failing_write(fd: int, data: bytes) -> int:
                nonlocal calls
                calls += 1
                if calls > 10:
                    raise OSError(errno.EIO, "injected")
                return os.write(fd, data[: min(16, len(data))])

            writer = San90RtaWriter.open_session(
                RecordingStorage(directory), file_prefix="failure", write_func=failing_write
            )
            with self.assertRaises(RecordingWriterError):
                writer.write_session_metadata({"large": "x" * 1000})
            writer.abort()
            report = San90RtaReader(writer.part_path).validate()
            self.assertTrue(report.recoverable)
            self.assertIsNotNone(report.file_header)


if __name__ == "__main__":
    unittest.main()
