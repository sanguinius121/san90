import unittest
from dataclasses import replace

import numpy as np

from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.spectrum_temporal import LatestSpectrumTemporalExchange, NativeSpectrumTemporalAccumulator


def metadata(now: int, generation: int = 1) -> RawTraceMetadata:
    return RawTraceMetadata(1, 2, 3, now, 1.0, 2.0, 3.0, 2.0, 1.0, 0.0,
                            RawAmplitudeMapping(0.5, -120.0), generation)


class SpectrumTemporalTests(unittest.TestCase):
    def test_native_uint8_max_includes_every_trace_and_latest_is_newest(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(3, interval_ns=10)
        packet = np.array([[10, 200, 20], [80, 30, 220], [40, 50, 60]], np.uint8)
        self.assertIsNone(accumulator.add_packet(packet, metadata(100)))
        result = accumulator.finalize_if_due(110)
        self.assertIsNotNone(result)
        np.testing.assert_array_equal(result.latest_trace_float32, packet[-1] * 0.5 - 120)
        np.testing.assert_array_equal(result.interval_max_trace_float32, packet.max(axis=0) * 0.5 - 120)
        self.assertEqual(result.traces_integrated, 3)
        self.assertEqual((result.first_receipt_monotonic_ns, result.last_receipt_monotonic_ns), (100, 100))

    def test_short_transient_missing_from_latest_survives_max(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=10)
        packet = np.array([[20, 20], [20, 240], [20, 20]], np.uint8)
        accumulator.add_packet(packet, metadata(1))
        result = accumulator.flush(9)
        self.assertGreater(result.interval_max_trace_float32[1], result.latest_trace_float32[1])

    def test_reconfiguration_discards_incomplete_interval(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=10)
        accumulator.add_packet(np.ones((1, 2), np.uint8), metadata(1, 1))
        accumulator.reset(generation=2)
        self.assertEqual(accumulator.discarded_incomplete_intervals, 1)
        self.assertIsNone(accumulator.flush(20))

    def test_newest_exchange_is_bounded_and_merges_replaced_maxima(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=1)
        accumulator.add_packet(np.array([[1, 200]], np.uint8), metadata(1))
        first = accumulator.flush(2)
        accumulator.add_packet(np.array([[220, 1]], np.uint8), metadata(3))
        second = accumulator.flush(4)
        exchange = LatestSpectrumTemporalExchange()
        exchange.publish(first); exchange.publish(second)
        result = exchange.take()
        self.assertEqual((exchange.frames_replaced, result.traces_integrated), (1, 2))
        self.assertGreater(result.interval_max_trace_float32[0], result.latest_trace_float32[1])
        self.assertGreater(result.interval_max_trace_float32[1], result.latest_trace_float32[1])
        self.assertIsNone(exchange.take())

    def test_incompatible_mapping_rejects_maximum_merge(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=1)
        accumulator.add_packet(np.array([[1, 200]], np.uint8), metadata(1))
        first = accumulator.flush(2)
        accumulator.add_packet(np.array([[220, 1]], np.uint8), metadata(3))
        second = replace(accumulator.flush(4), offset_to_dbm=-119.0)
        exchange = LatestSpectrumTemporalExchange()
        exchange.publish(first)
        exchange.publish(second)
        result = exchange.take()
        self.assertEqual(result.traces_integrated, 1)
        self.assertEqual(exchange.frames_displaced, 1)
        self.assertEqual(exchange.compatible_maximum_merges, 0)
        self.assertEqual(exchange.incompatible_merge_rejections, 1)

    def test_missed_deadlines_skip_empty_intervals_without_drift(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=10)
        accumulator.add_packet(np.ones((1, 2), np.uint8), metadata(100))
        first = accumulator.finalize_if_due(135)
        self.assertEqual((first.interval_start_monotonic_ns, first.interval_end_monotonic_ns), (100, 110))
        self.assertEqual(accumulator.missed_interval_deadlines, 2)
        accumulator.add_packet(np.ones((1, 2), np.uint8), metadata(135))
        second = accumulator.finalize_if_due(140)
        self.assertEqual((second.interval_start_monotonic_ns, second.interval_end_monotonic_ns), (130, 140))
        self.assertEqual(accumulator.completed_intervals, 2)

    def test_temporal_timing_metrics_are_recorded(self) -> None:
        accumulator = NativeSpectrumTemporalAccumulator(2, interval_ns=10)
        accumulator.add_packet(np.ones((1, 2), np.uint8), metadata(100))
        accumulator.add_packet(np.ones((1, 2), np.uint8), metadata(105))
        accumulator.flush(110)
        self.assertEqual((accumulator.receipt_span_total_ns, accumulator.receipt_span_min_ns, accumulator.receipt_span_max_ns), (5, 5, 5))
        self.assertGreater(accumulator.conversion_total_ns, 0)
        self.assertGreater(accumulator.finalization_total_ns, 0)

    def test_26_point_temporal_payload_preserves_original_bins(self) -> None:
        accumulator=NativeSpectrumTemporalAccumulator(26,interval_ns=10)
        packet=np.arange(52,dtype=np.uint8).reshape(2,26)
        accumulator.add_packet(packet,metadata(1));frame=accumulator.flush(10)
        self.assertEqual((frame.point_count,frame.latest_trace_float32.size,frame.interval_max_trace_float32.size),(26,26,26))


if __name__ == "__main__":
    unittest.main()
