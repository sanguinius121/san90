import unittest

import numpy as np

from backend.analyzer.models import FrameType, SpectrumFrame
from backend.analyzer.waterfall import TimedWaterfallBatchProducer, WaterfallRateConfig, waterfall_rate_for_profile
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata


def frame(sequence: int, points: int = 4, generation: int = 1) -> SpectrumFrame:
    return SpectrumFrame(sequence, 1_000 + sequence, np.zeros(points, np.float32), points, 100.0, 150.0, 200.0, 100.0, 10.0, None, 0.0, None, FrameType.CURRENT, configuration_generation=generation)


class WaterfallBatchTests(unittest.TestCase):
    def test_actual_profile_metadata_selects_verified_rates(self) -> None:
        safe = waterfall_rate_for_profile(60_306.091, 3328)
        fast = waterfall_rate_for_profile(241_224.365, 832)
        requested_fast_but_actual_safe = waterfall_rate_for_profile(60_306.091, 3328)
        self.assertEqual(safe, WaterfallRateConfig(60.0, 60.0, 1))
        self.assertEqual(fast, WaterfallRateConfig(240.0, 60.0, 4))
        self.assertEqual(requested_fast_but_actual_safe, safe)

    def test_native_packet_is_segmented_at_row_deadlines(self) -> None:
        producer = TimedWaterfallBatchProducer(2, 3, WaterfallRateConfig(250.0, 125.0, 2))
        packet = np.array([[value, 20 - value] for value in range(10)], dtype=np.uint8)
        metadata = RawTraceMetadata(
            sequence=9,
            device_timestamp_ns=109_000_000,
            host_timestamp_ns=209_000_000,
            receipt_monotonic_ns=9_000_000,
            start_frequency_hz=100.0,
            center_frequency_hz=150.0,
            stop_frequency_hz=200.0,
            span_hz=100.0,
            rbw_hz=241_224.0,
            reference_level_dbm=0.0,
            mapping=RawAmplitudeMapping(1.0, -100.0),
            configuration_generation=3,
        )
        producer.add_packet(packet, metadata, trace_timestamp_step_ns=1_000_000)
        # A later trace closes the third, still-incomplete row; the first two
        # rows form a batch and must contain native max-holds of traces 0..3
        # and 4..7 respectively.
        producer.add_trace(
            np.array([1, 1], np.uint8), frame(10, 2, 3),
            receipt_monotonic_ns=12_000_000, host_timestamp_ns=212_000_000,
        )
        batch = producer.exchange.take_latest()
        self.assertIsNotNone(batch)
        assert batch is not None
        np.testing.assert_array_equal(batch.values, [[3, 20], [7, 16]])
        metrics = producer.metrics()
        self.assertEqual(metrics.completed_rows, 3)
        self.assertEqual(metrics.traces_integrated, 11)
        self.assertEqual(metrics.minimum_traces_per_row, 2)
        self.assertEqual(metrics.maximum_traces_per_row, 4)

    def test_deadlines_max_hold_and_trace_accounting(self) -> None:
        producer = TimedWaterfallBatchProducer(4, 1, WaterfallRateConfig(100.0, 50.0, 2))
        traces = (
            (0, [1, 5, 2, 0]),
            (4_000_000, [7, 3, 4, 1]),
            (9_000_000, [4, 9, 3, 8]),
            (10_000_000, [2, 2, 2, 2]),
            (15_000_000, [3, 1, 8, 4]),
            (20_000_000, [1, 1, 1, 1]),
        )
        for sequence, (when, values) in enumerate(traces):
            producer.add_trace(np.array(values, np.uint8), frame(sequence), receipt_monotonic_ns=when, host_timestamp_ns=10_000 + when)
        batch = producer.exchange.take_latest()
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.values.shape, (2, 4))
        self.assertTrue(batch.values.flags.c_contiguous)
        np.testing.assert_array_equal(batch.values[0], [7, 9, 4, 8])
        np.testing.assert_array_equal(batch.values[1], [3, 2, 8, 4])
        metrics = producer.metrics()
        self.assertEqual(metrics.completed_rows, 2)
        self.assertEqual(metrics.minimum_traces_per_row, 2)
        self.assertEqual(metrics.maximum_traces_per_row, 3)
        self.assertEqual(metrics.mean_traces_per_row, 2.5)

    def test_missed_deadlines_do_not_create_empty_rows(self) -> None:
        producer = TimedWaterfallBatchProducer(2, 1, WaterfallRateConfig(100.0, 100.0, 1))
        producer.add_trace(np.array([1, 2], np.uint8), frame(0, 2), receipt_monotonic_ns=0, host_timestamp_ns=1)
        producer.add_trace(np.array([3, 4], np.uint8), frame(1, 2), receipt_monotonic_ns=50_000_000, host_timestamp_ns=2)
        self.assertEqual(producer.metrics().completed_rows, 1)
        self.assertEqual(producer.metrics().missed_row_deadlines, 4)
        self.assertEqual(producer.metrics().empty_rows, 4)

    def test_reconfiguration_discards_incomplete_data_and_changes_points(self) -> None:
        producer = TimedWaterfallBatchProducer(4, 1, WaterfallRateConfig(100.0, 50.0, 2))
        producer.add_trace(np.ones(4, np.uint8), frame(0), receipt_monotonic_ns=0, host_timestamp_ns=1)
        producer.add_trace(np.ones(4, np.uint8), frame(1), receipt_monotonic_ns=10_000_000, host_timestamp_ns=2)
        producer.reconfigure(2, 2, WaterfallRateConfig(200.0, 100.0, 2))
        metrics = producer.metrics()
        self.assertEqual(metrics.discarded_incomplete_rows, 1)
        self.assertEqual(metrics.discarded_incomplete_batch_rows, 1)
        with self.assertRaisesRegex(ValueError, 'active configuration'):
            producer.add_trace(np.ones(2, np.uint8), frame(2, 2, 1), receipt_monotonic_ns=20_000_000, host_timestamp_ns=3)

    def test_slow_consumer_replaces_whole_batches_and_rows(self) -> None:
        producer = TimedWaterfallBatchProducer(2, 1, WaterfallRateConfig(100.0, 100.0, 1))
        for sequence, when in enumerate((0, 10_000_000, 20_000_000, 30_000_000)):
            producer.add_trace(np.full(2, sequence, np.uint8), frame(sequence, 2), receipt_monotonic_ns=when, host_timestamp_ns=sequence)
        metrics = producer.metrics()
        self.assertEqual(metrics.completed_batches, 3)
        self.assertEqual(metrics.replaced_batches, 2)
        self.assertEqual(metrics.replaced_rows, 2)
        latest = producer.exchange.take_latest()
        assert latest is not None
        self.assertEqual(latest.batch_sequence, 2)

    def test_rate_configuration_rejects_inconsistent_values(self) -> None:
        with self.assertRaisesRegex(ValueError, 'must equal'):
            WaterfallRateConfig(240.0, 60.0, 3)


if __name__ == '__main__':
    unittest.main()
