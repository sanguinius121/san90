from __future__ import annotations

import unittest

import numpy as np

from backend.analyzer.buffers import IntervalMaxHoldBuffer, LatestFrameBuffer
from backend.analyzer.models import FrameType, SpectrumFrame


def make_frame(sequence: int, values: list[float]) -> SpectrumFrame:
    array = np.array(values, dtype=np.float32)
    return SpectrumFrame(
        sequence=sequence,
        timestamp_ns=sequence,
        values=array,
        point_count=array.size,
        start_frequency_hz=0.0,
        center_frequency_hz=1.0,
        stop_frequency_hz=2.0,
        span_hz=2.0,
        rbw_hz=1.0,
        vbw_hz=None,
        reference_level_dbm=0.0,
        sweep_time_s=None,
    )


class LatestFrameBufferTests(unittest.TestCase):
    def test_newest_unread_frame_replaces_old_frame(self) -> None:
        buffer = LatestFrameBuffer()
        buffer.publish(make_frame(1, [-10, -20]))
        buffer.publish(make_frame(2, [-30, -40]))
        frame = buffer.read()
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.sequence, 2)
        self.assertEqual(buffer.replaced, 1)
        self.assertIsNone(buffer.read())

    def test_published_storage_is_detached(self) -> None:
        buffer = LatestFrameBuffer()
        source = make_frame(1, [-10, -20])
        buffer.publish(source)
        source.values[:] = 0
        frame = buffer.read()
        assert frame is not None
        np.testing.assert_array_equal(frame.values, [-10, -20])


class IntervalMaxHoldBufferTests(unittest.TestCase):
    def test_accumulates_and_resets_interval(self) -> None:
        buffer = IntervalMaxHoldBuffer()
        buffer.accumulate(make_frame(1, [-30, -10, -40]))
        buffer.accumulate(make_frame(2, [-20, -15, -35]))
        frame = buffer.take()
        assert frame is not None
        self.assertEqual(frame.frame_type, FrameType.MAX_HOLD)
        np.testing.assert_array_equal(frame.values, [-20, -10, -35])
        self.assertIsNone(buffer.take())


if __name__ == "__main__":
    unittest.main()
