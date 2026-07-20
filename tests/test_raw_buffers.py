import unittest

import numpy as np

from backend.analyzer.raw_buffers import DisplaySnapshotExchange, RawAmplitudeMapping, RawRtaAccumulator, RawTraceMetadata


def metadata(sequence: int = 1) -> RawTraceMetadata:
    return RawTraceMetadata(sequence, 100, 200, 300, 1.0, 2.0, 3.0, 2.0, 10.0, 0.0, RawAmplitudeMapping(0.5, -120.0))


class RawBufferTests(unittest.TestCase):
    def test_native_mapping_and_interval_max_match_dbm_max(self) -> None:
        raw = np.array([[0, 20, 80], [10, 15, 100]], dtype=np.uint8)
        accumulator = RawRtaAccumulator(3)
        accumulator.update(raw, metadata())
        np.testing.assert_allclose(accumulator.copy_latest_dbm(), [-115.0, -112.5, -70.0])
        np.testing.assert_allclose(accumulator.copy_interval_max_dbm(), [-115.0, -110.0, -70.0])

    def test_reuses_acquisition_storage_and_resets_interval(self) -> None:
        accumulator = RawRtaAccumulator(3328)
        latest_id = id(accumulator.latest_raw)
        maximum_id = id(accumulator.interval_max_raw)
        accumulator.update(np.zeros((4, 3328), dtype=np.uint8), metadata())
        accumulator.update(np.ones((4, 3328), dtype=np.uint8), metadata(2))
        self.assertEqual(id(accumulator.latest_raw), latest_id)
        self.assertEqual(id(accumulator.interval_max_raw), maximum_id)

    def test_snapshot_exchange_is_newest_only(self) -> None:
        accumulator = RawRtaAccumulator(4)
        exchange = DisplaySnapshotExchange(4)
        accumulator.update(np.full((2, 4), 10, dtype=np.uint8), metadata())
        self.assertTrue(exchange.publish(accumulator, spectrum=True, waterfall=True))
        accumulator.update(np.full((2, 4), 20, dtype=np.uint8), metadata(2))
        self.assertTrue(exchange.publish(accumulator, spectrum=True, waterfall=True))
        self.assertEqual(exchange.replaced, 1)
        snapshot = exchange.take_latest()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        np.testing.assert_allclose(snapshot.spectrum_float32, -110.0)
        np.testing.assert_equal(snapshot.waterfall_uint8, 20)
        self.assertIsNone(exchange.take_latest())

    def test_profile_change_uses_new_point_sized_buffers(self) -> None:
        wide = RawRtaAccumulator(3328)
        wide_exchange = DisplaySnapshotExchange(3328)
        wide.update(np.full((2, 3328), 10, dtype=np.uint8), metadata())
        self.assertTrue(wide_exchange.publish(wide, spectrum=True, waterfall=True))
        wide_snapshot = wide_exchange.take_latest()
        assert wide_snapshot is not None
        self.assertEqual(wide_snapshot.spectrum_float32.shape, (3328,))

        narrow = RawRtaAccumulator(832)
        narrow_exchange = DisplaySnapshotExchange(832)
        narrow.update(np.full((2, 832), 20, dtype=np.uint8), metadata(2))
        self.assertTrue(narrow_exchange.publish(narrow, spectrum=True, waterfall=True))
        narrow_snapshot = narrow_exchange.take_latest()
        assert narrow_snapshot is not None
        self.assertEqual(narrow_snapshot.spectrum_float32.shape, (832,))
        self.assertEqual(narrow_snapshot.waterfall_uint8.shape, (832,))


if __name__ == '__main__':
    unittest.main()
