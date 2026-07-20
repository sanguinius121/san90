import struct
import unittest

import numpy as np

from backend.analyzer.models import SpectrumTemporalFrame, WaterfallBatch
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.api.protocol import HEADER_SIZE, MESSAGE_SPECTRUM, MESSAGE_SPECTRUM_TEMPORAL, MESSAGE_WATERFALL, SPECTRUM_TEMPORAL_HEADER_SIZE, WATERFALL_BATCH_HEADER_SIZE, pack_spectrum, pack_spectrum_temporal, pack_waterfall, pack_waterfall_batch, unpack_header


def metadata() -> RawTraceMetadata:
    return RawTraceMetadata(42, 123, 456, 789, 2.399e9, 2.45e9, 2.501e9, 102e6, 30e3, -10.0, RawAmplitudeMapping(0.5, -120.0))


class BinaryProtocolTests(unittest.TestCase):
    def test_float32_spectrum_round_trip(self) -> None:
        values = np.linspace(-110, -10, 3328, dtype=np.float32)
        message = pack_spectrum('san90', metadata(), values)
        header = unpack_header(message)
        self.assertEqual(HEADER_SIZE, 96)
        self.assertEqual(header['message_type'], MESSAGE_SPECTRUM)
        self.assertEqual(header['point_count'], 3328)
        decoded = np.frombuffer(message, dtype='<f4', offset=HEADER_SIZE)
        np.testing.assert_array_equal(decoded, values)

    def test_uint8_waterfall_round_trip(self) -> None:
        values = np.arange(3328, dtype=np.uint16).astype(np.uint8)
        message = pack_waterfall('san90', metadata(), values)
        header = unpack_header(message)
        self.assertEqual(header['message_type'], MESSAGE_WATERFALL)
        np.testing.assert_array_equal(np.frombuffer(message, dtype=np.uint8, offset=HEADER_SIZE), values)

    def test_temporal_spectrum_pair_round_trip(self) -> None:
        latest = np.array([-100, -90, -80], np.float32)
        maximum = np.array([-70, -40, -60], np.float32)
        frame = SpectrumTemporalFrame(7, 11, 3, 100, 200, 300, 400, 17, latest, maximum,
            2.399e9, 2.45e9, 2.501e9, 102e6, 60_306.0, -10.0, 0.5, -120.0)
        message = pack_spectrum_temporal("simulator", frame)
        header = unpack_header(message)
        self.assertEqual((SPECTRUM_TEMPORAL_HEADER_SIZE, header["message_type"]), (128, MESSAGE_SPECTRUM_TEMPORAL))
        self.assertEqual((header["traces_integrated"], header["configuration_generation"]), (17, 7))
        decoded = np.frombuffer(message, "<f4", offset=SPECTRUM_TEMPORAL_HEADER_SIZE)
        np.testing.assert_array_equal(decoded[:3], latest)
        np.testing.assert_array_equal(decoded[3:], maximum)

    def test_malformed_temporal_spectrum_is_rejected(self) -> None:
        frame = SpectrumTemporalFrame(1, 1, 2, 1, 2, 3, None, 1,
            np.array([-1, -2], np.float32), np.array([-1, -2], np.float32),
            1.0, 2.0, 3.0, 2.0, 1.0, 0.0, 1.0, 0.0)
        message = bytearray(pack_spectrum_temporal("simulator", frame))
        struct.pack_into("<I", message, 68, 1)
        with self.assertRaisesRegex(ValueError, "payload"):
            unpack_header(message)

    def test_malformed_identity_and_payload_length_are_rejected(self) -> None:
        message = bytearray(pack_waterfall('simulator', metadata(), np.ones(8, np.uint8)))
        message[0:4] = b'NOPE'
        with self.assertRaises(ValueError): unpack_header(message)
        message[0:4] = b'SAN9'
        struct.pack_into('<I', message, 48, 999)
        with self.assertRaises(ValueError): unpack_header(message)

    def test_non_finite_metadata_is_rejected(self) -> None:
        invalid = RawTraceMetadata(1, 1, 1, 1, float('nan'), 1.0, 2.0, 2.0, 1.0, 0.0, RawAmplitudeMapping(1.0, 0.0))
        with self.assertRaises(ValueError): pack_waterfall('san90', invalid, np.ones(8, np.uint8))

    def test_four_row_dynamic_waterfall_batches(self) -> None:
        for points in (832, 3328):
            values = np.arange(4 * points, dtype=np.uint32).astype(np.uint8).reshape(4, points)
            batch = WaterfallBatch(7, 9, 36, 4, points, 456, 123, 4_166_667, 2.399e9, 2.45e9, 2.501e9, 102e6, 241_224.365, 0.0, values.copy())
            message = pack_waterfall_batch('simulator', batch)
            header = unpack_header(message)
            self.assertEqual(WATERFALL_BATCH_HEADER_SIZE, 120)
            self.assertEqual(header['version'], 3)
            self.assertEqual(header['row_count'], 4)
            self.assertEqual(header['point_count'], points)
            self.assertEqual(header['first_row_sequence'], 36)
            decoded = np.frombuffer(message, np.uint8, offset=WATERFALL_BATCH_HEADER_SIZE).reshape(4, points)
            np.testing.assert_array_equal(decoded, values)

    def test_malformed_batch_dimensions_are_rejected(self) -> None:
        values = np.ones((4, 832), np.uint8)
        batch = WaterfallBatch(1, 1, 1, 4, 832, 2, 3, 4_166_667, 1.0, 2.0, 3.0, 2.0, 1.0, 0.0, values.copy())
        message = bytearray(pack_waterfall_batch('simulator', batch))
        struct.pack_into('<I', message, 60, 0)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            unpack_header(message)
        message = bytearray(pack_waterfall_batch('simulator', batch))
        struct.pack_into('<I', message, 68, 1)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            unpack_header(message)
        message = bytearray(pack_waterfall_batch('simulator', batch))
        struct.pack_into('<Q', message, 52, 0)
        with self.assertRaisesRegex(ValueError, 'row period'):
            unpack_header(message)


if __name__ == '__main__':
    unittest.main()
