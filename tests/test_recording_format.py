from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.recording.format import (
    BYTE_ORDER_MARKER,
    CONFIG_HEADER_STRUCT,
    CONFIG_RECORD_HEADER_SIZE,
    END_HEADER_STRUCT,
    END_RECORD_HEADER_SIZE,
    EVENT_HEADER_STRUCT,
    EVENT_RECORD_HEADER_SIZE,
    FILE_HEADER_SIZE,
    FILE_HEADER_STRUCT,
    GAP_HEADER_STRUCT,
    GAP_RECORD_HEADER_SIZE,
    MAX_RECORD_HEADER_LENGTH,
    RECORD_PREFIX_SIZE,
    RECORD_PREFIX_STRUCT,
    TRACE_HEADER_STRUCT,
    TRACE_RECORD_HEADER_SIZE,
    Crc32c,
    RecordingFormatError,
    crc32c,
    pack_configuration_record,
    pack_file_header,
    pack_record,
    unpack_file_header,
    unpack_record_prefix,
)
from backend.recording.models import (
    ConfigRecordFlags,
    ConfigurationRecord,
    EndRecord,
    EventRecord,
    GapRecord,
    GenericRecord,
    RecordType,
    SessionMetadataRecord,
    TraceBatchRecord,
)
from backend.recording.reader import San90RtaReader
from tests.recording_fixtures import CREATED_NS, FixtureBuilder, SESSION_UUID, valid_fixture


def _rewrite_file_header_crc(data: bytearray) -> None:
    data[92:96] = bytes(4)
    struct.pack_into("<I", data, 92, crc32c(data[:FILE_HEADER_SIZE]))


def _rewrite_record_header_crc(record: bytearray) -> None:
    header_length = struct.unpack_from("<I", record, 8)[0]
    record[28:32] = bytes(4)
    struct.pack_into("<I", record, 28, crc32c(record[:header_length]))


class RecordingStructTests(unittest.TestCase):
    def test_exact_struct_sizes_and_total_headers(self) -> None:
        self.assertEqual(FILE_HEADER_STRUCT.size, 96)
        self.assertEqual(RECORD_PREFIX_STRUCT.size, 48)
        self.assertEqual(RECORD_PREFIX_SIZE + CONFIG_HEADER_STRUCT.size, 168)
        self.assertEqual(RECORD_PREFIX_SIZE + TRACE_HEADER_STRUCT.size, 136)
        self.assertEqual(RECORD_PREFIX_SIZE + GAP_HEADER_STRUCT.size, 128)
        self.assertEqual(RECORD_PREFIX_SIZE + EVENT_HEADER_STRUCT.size, 96)
        self.assertEqual(RECORD_PREFIX_SIZE + END_HEADER_STRUCT.size, 160)
        self.assertEqual(
            (
                CONFIG_RECORD_HEADER_SIZE,
                TRACE_RECORD_HEADER_SIZE,
                GAP_RECORD_HEADER_SIZE,
                EVENT_RECORD_HEADER_SIZE,
                END_RECORD_HEADER_SIZE,
            ),
            (168, 136, 128, 96, 160),
        )

    def test_documented_offsets_are_little_endian_and_unpadded(self) -> None:
        header = pack_file_header(creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID)
        self.assertEqual(header[:8], b"SAN90RTA")
        self.assertEqual(struct.unpack_from("<H", header, 8)[0], 1)
        self.assertEqual(struct.unpack_from("<I", header, 12)[0], BYTE_ORDER_MARKER)
        self.assertEqual(struct.unpack_from("<I", header, 16)[0], 96)
        self.assertEqual(header[32:48], SESSION_UUID.bytes)
        self.assertEqual(struct.unpack_from("<I", header, 48)[0], 48)
        self.assertEqual(struct.unpack_from("<I", header, 52)[0], 65_536)
        self.assertEqual(struct.unpack_from("<Q", header, 64)[0], 1 << 30)

    def test_type_specific_documented_offsets(self) -> None:
        builder = FixtureBuilder()
        config = builder.add_config()
        self.assertEqual(struct.unpack_from("<Q", config, 48)[0], 1)
        self.assertEqual(struct.unpack_from("<Q", config, 56)[0], 7)
        self.assertEqual(struct.unpack_from("<Q", config, 64)[0], 100)
        self.assertEqual(struct.unpack_from("<d", config, 88)[0], 2_450_000_000.0)
        self.assertEqual(struct.unpack_from("<I", config, 160)[0], 4)
        self.assertEqual(struct.unpack_from("<I", config, 164)[0], 8)

        trace = builder.add_trace()
        self.assertEqual(struct.unpack_from("<Q", trace, 48)[0], 1)
        self.assertEqual(struct.unpack_from("<Q", trace, 64)[0], 100)
        self.assertEqual(struct.unpack_from("<I", trace, 72)[0], 2)
        self.assertEqual(struct.unpack_from("<I", trace, 76)[0], 4)
        self.assertEqual(struct.unpack_from("<Q", trace, 104)[0], 130_760)
        self.assertEqual(struct.unpack_from("<d", trace, 120)[0], 16_384.0)

        gap = builder.add_gap()
        self.assertEqual(struct.unpack_from("<Q", gap, 64)[0], 102)
        self.assertEqual(struct.unpack_from("<Q", gap, 72)[0], 105)
        self.assertEqual(struct.unpack_from("<H", gap, 120)[0], 2)

        event = builder.add_event()
        self.assertEqual(struct.unpack_from("<H", event, 64)[0], 10)
        self.assertEqual(struct.unpack_from("<H", event, 66)[0], 1)
        self.assertEqual(struct.unpack_from("<Q", event, 72)[0], 1)

        complete = builder.finish()
        end = complete[-END_RECORD_HEADER_SIZE:]
        self.assertEqual(struct.unpack_from("<H", end, 64)[0], 2)
        self.assertEqual(struct.unpack_from("<Q", end, 72)[0], 5)
        self.assertEqual(struct.unpack_from("<Q", end, 144)[0], 1_000_000_000)

    def test_known_crc32c_vector_and_supported_buffer_types(self) -> None:
        expected = 0xE3069283
        self.assertEqual(crc32c(b"123456789"), expected)
        self.assertEqual(crc32c(bytearray(b"123456789")), expected)
        self.assertEqual(crc32c(memoryview(b"123456789")), expected)
        rolling = Crc32c()
        rolling.update(b"1234")
        rolling.update(memoryview(b"56789"))
        self.assertEqual(rolling.value, expected)

    def test_file_header_round_trip_and_crc(self) -> None:
        packed = pack_file_header(creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID)
        parsed = unpack_file_header(packed)
        self.assertEqual(parsed.session_uuid, SESSION_UUID)
        self.assertEqual(parsed.creation_unix_ns, CREATED_NS)
        damaged = bytearray(packed)
        damaged[24] ^= 1
        with self.assertRaisesRegex(RecordingFormatError, "CRC32C"):
            unpack_file_header(damaged)

    def test_empty_and_nonempty_payload_crc(self) -> None:
        empty = pack_record(record_type=0x7000, record_index=1)
        nonempty = pack_record(record_type=0x7000, record_index=2, payload=b"payload")
        self.assertEqual(unpack_record_prefix(empty, offset=0).payload_crc32c, 0)
        self.assertEqual(unpack_record_prefix(nonempty, offset=0).payload_crc32c, crc32c(b"payload"))


class RecordingReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="san90-recording-test-")
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        path = self.directory / name
        path.write_bytes(data)
        return path

    def test_every_record_type_pack_and_unpack(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_event()
        builder.add_config()
        builder.add_trace()
        builder.add_gap(expected_sequence=102, next_sequence=102, lost=0)
        path = self.write("all.san90rta", builder.finish())
        records = list(San90RtaReader(path).iter_records())
        self.assertEqual(
            [type(record) for record in records],
            [SessionMetadataRecord, EventRecord, ConfigurationRecord, TraceBatchRecord, GapRecord, EndRecord],
        )

    def test_unknown_record_type_is_crc_validated_and_skipped(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_unknown()
        builder.add_config()
        builder.add_trace()
        path = self.write("unknown.san90rta", builder.finish())
        records = list(San90RtaReader(path).iter_records())
        unknown = next(record for record in records if isinstance(record, GenericRecord))
        self.assertEqual(unknown.prefix.record_type, 0x7000)
        self.assertTrue(San90RtaReader(path).validate().valid)

    def test_unsupported_major_and_invalid_byte_order_are_rejected(self) -> None:
        unsupported = pack_file_header(
            creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID, format_major=2
        )
        with self.assertRaisesRegex(RecordingFormatError, "major"):
            unpack_file_header(unsupported)
        invalid = bytearray(pack_file_header(creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID))
        struct.pack_into("<I", invalid, 12, 0x04030201)
        _rewrite_file_header_crc(invalid)
        with self.assertRaisesRegex(RecordingFormatError, "byte-order"):
            unpack_file_header(invalid)

    def test_invalid_header_and_total_lengths_are_rejected(self) -> None:
        record = bytearray(pack_record(record_type=0x7000, record_index=1, payload=b"x"))
        struct.pack_into("<I", record, 8, MAX_RECORD_HEADER_LENGTH + 1)
        with self.assertRaisesRegex(RecordingFormatError, "header length"):
            unpack_record_prefix(record, offset=96)
        record = bytearray(pack_record(record_type=0x7000, record_index=1, payload=b"x"))
        struct.pack_into("<Q", record, 40, len(record) + 1)
        with self.assertRaisesRegex(RecordingFormatError, "does not equal"):
            unpack_record_prefix(record, offset=96)

    def test_truncated_prefix_type_header_and_payload_offsets(self) -> None:
        header = pack_file_header(creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID)
        prefix_path = self.write("prefix.san90rta.part", header + b"S9RR")
        prefix_report = San90RtaReader(prefix_path).validate()
        self.assertEqual(prefix_report.first_invalid_offset, 96)
        self.assertIn("truncated_record_prefix", [issue.code for issue in prefix_report.issues])

        builder = FixtureBuilder()
        config = builder.add_config()
        header_path = self.write("header.san90rta.part", builder.header + config[:60])
        header_report = San90RtaReader(header_path).validate()
        self.assertEqual(header_report.first_invalid_offset, 96)
        self.assertIn("truncated_record_header", [issue.code for issue in header_report.issues])

        builder = FixtureBuilder()
        session = builder.add_session()
        payload_path = self.write("payload.san90rta.part", builder.header + session[:-2])
        payload_report = San90RtaReader(payload_path).validate()
        self.assertEqual(payload_report.first_invalid_offset, 96)
        self.assertIn("truncated_payload", [issue.code for issue in payload_report.issues])

    def test_corrupted_record_header_and_payload_crc_stop_at_record(self) -> None:
        builder = FixtureBuilder()
        session = bytearray(builder.add_session())
        session[5] ^= 1
        header_path = self.write("header-crc.san90rta", builder.header + session)
        header_report = San90RtaReader(header_path).validate()
        self.assertEqual(header_report.first_invalid_offset, 96)
        self.assertEqual(header_report.issues[0].checksum_kind, "record_header")

        builder = FixtureBuilder()
        session = bytearray(builder.add_session())
        session[-1] ^= 1
        payload_path = self.write("payload-crc.san90rta", builder.header + session)
        payload_report = San90RtaReader(payload_path).validate()
        self.assertEqual(payload_report.first_invalid_offset, 96)
        self.assertEqual(payload_report.issues[0].checksum_kind, "payload")

    def test_config_must_precede_trace_and_reference_must_exist(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_trace()
        builder.add_config()
        report = San90RtaReader(self.write("late-config.san90rta", builder.finish())).validate()
        self.assertIn("missing_config", [issue.code for issue in report.issues])

        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config()
        builder.add_trace(config_id=99)
        report = San90RtaReader(self.write("missing-config.san90rta", builder.finish())).validate()
        self.assertIn("missing_config", [issue.code for issue in report.issues])

    def test_generation_and_frame_width_mismatch(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config()
        builder.add_trace(generation=8, frame_width=2, payload=b"\x01\x02\x03\x04")
        report = San90RtaReader(self.write("mismatch.san90rta", builder.finish())).validate()
        codes = [issue.code for issue in report.issues]
        self.assertIn("generation_mismatch", codes)
        self.assertIn("frame_width_mismatch", codes)

    def test_trace_payload_dimensions_are_checked_before_payload_read(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config()
        trace = bytearray(builder.add_trace())
        struct.pack_into("<I", trace, 72, 3)
        _rewrite_record_header_crc(trace)
        data = builder.header + builder.records[0] + builder.records[1] + trace
        report = San90RtaReader(self.write("dimensions.san90rta", data)).validate()
        self.assertEqual(report.issues[0].code, "invalid_trace_payload_length")

    def test_sequence_continuity_and_explicit_gap(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config()
        builder.add_trace()
        builder.add_trace(first_sequence=105)
        report = San90RtaReader(self.write("sequence.san90rta", builder.finish())).validate()
        self.assertIn("sequence_discontinuity", [issue.code for issue in report.issues])

        path = self.write("gap.san90rta", valid_fixture(gap=True))
        report = San90RtaReader(path).validate()
        self.assertTrue(report.valid, report.issues)
        self.assertEqual((report.gap_count, report.lost_trace_count), (1, 3))

    def test_end_counters_and_rolling_crc(self) -> None:
        valid = San90RtaReader(self.write("valid.san90rta", valid_fixture())).validate()
        self.assertTrue(valid.valid, valid.issues)
        self.assertTrue(valid.complete)
        self.assertTrue(valid.clean_finalization)
        self.assertEqual(valid.end_record.rolling_crc32c, valid.end_record.computed_rolling_crc32c)

        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config()
        builder.add_trace()
        counters = builder.finish(trace_count=999, rolling_override=0)
        report = San90RtaReader(self.write("bad-end.san90rta", counters)).validate()
        codes = [issue.code for issue in report.issues]
        self.assertIn("end_counter_mismatch", codes)
        self.assertIn("rolling_crc", codes)

    def test_record_after_end_is_rejected(self) -> None:
        data = valid_fixture() + pack_record(record_type=0x7000, record_index=5)
        report = San90RtaReader(self.write("after-end.san90rta", data)).validate()
        self.assertIn("record_after_end", [issue.code for issue in report.issues])

    def test_recoverable_truncated_part_and_multi_configuration(self) -> None:
        truncated = valid_fixture()[:-20]
        report = San90RtaReader(self.write("recover.san90rta.part", truncated)).validate()
        self.assertFalse(report.valid)
        self.assertTrue(report.recoverable)
        self.assertIsNotNone(report.first_invalid_offset)

        reader = San90RtaReader(self.write("multi.san90rta", valid_fixture(multiple_configs=True)))
        report = reader.validate()
        self.assertTrue(report.valid, report.issues)
        self.assertEqual(
            [(config.config_id, config.configuration_generation, config.frame_width) for config in report.configurations],
            [(1, 7, 4), (2, 8, 2)],
        )
        self.assertEqual(len(list(reader.iter_trace_batches())), 2)

    def test_frequency_axis_and_dbm_reconstruction_apply_offset_once(self) -> None:
        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config(amplitude_offset_db=2.0)
        builder.add_trace(trace_count=1, payload=b"\x00\x02\x04\x06")
        reader = San90RtaReader(self.write("positive.san90rta", builder.finish()))
        batch = next(reader.iter_trace_batches())
        np.testing.assert_allclose(reader.reconstruct_dbm(batch, 0), [-98, -97, -96, -95])
        np.testing.assert_allclose(
            reader.reconstruct_frequency_axis(batch),
            [2_412_500_000, 2_437_500_000, 2_462_500_000, 2_487_500_000],
        )
        with self.assertRaises(IndexError):
            reader.reconstruct_dbm(batch, 1)

        builder = FixtureBuilder()
        builder.add_session()
        builder.add_config(amplitude_offset_db=-3.0)
        builder.add_trace(trace_count=1, payload=b"\x00\x02\x04\x06")
        reader = San90RtaReader(self.write("negative.san90rta", builder.finish()))
        batch = next(reader.iter_trace_batches())
        np.testing.assert_allclose(reader.reconstruct_dbm(batch, 0), [-103, -102, -101, -100])
        self.assertNotEqual(float(reader.reconstruct_dbm(batch, 0)[0]), -106.0)

    def test_configuration_numeric_validation_and_json_canonicalization(self) -> None:
        with self.assertRaisesRegex(RecordingFormatError, "non-finite"):
            pack_configuration_record(
                record_index=1,
                config_id=1,
                configuration_generation=1,
                effective_first_sequence=0,
                effective_host_unix_ns=1,
                effective_host_monotonic_ns=1,
                center_frequency_hz=float("nan"),
                start_frequency_hz=1,
                stop_frequency_hz=2,
                span_hz=1,
                rbw_hz=1,
                vbw_hz=0,
                sweep_time_s=0,
                reference_level_dbm=0,
                hardware_scale_db_per_code=1,
                hardware_offset_dbm=0,
                software_amplitude_offset_db=0,
                frame_width=2,
                fft_size=2,
                flags=ConfigRecordFlags.OUTER_BIN_EDGES,
            )
        first = pack_record(record_type=0x7000, record_index=1, payload=b'{"a":1,"b":2}')
        second = pack_record(record_type=0x7000, record_index=1, payload=b'{"a":1,"b":2}')
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
