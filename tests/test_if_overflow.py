from __future__ import annotations

import unittest

from backend.api.service import AnalyzerService
from backend.analyzer.if_overflow import IfOverflowLatch, classify_rta_read_status
from backend.analyzer.htra import API_NO_ERROR, API_WARNING_IF_OVERFLOW
from backend.analyzer.simulator import SimulatorSource


class IfOverflowTests(unittest.TestCase):
    def test_sdk_minus_twelve_is_recoverable_and_trace_is_processed(self) -> None:
        result = classify_rta_read_status(API_WARNING_IF_OVERFLOW)
        latch = IfOverflowLatch(hold_seconds=0.9)
        if result.if_overflow:
            latch.note_overflow(now_ns=1_000_000_000)
        self.assertTrue(result.if_overflow)
        self.assertTrue(result.process_trace)
        self.assertFalse(result.fatal)
        self.assertTrue(latch.active(now_ns=1_500_000_000))

    def test_latch_activates_holds_and_expires_on_monotonic_time(self) -> None:
        latch = IfOverflowLatch(hold_seconds=0.9)
        latch.note_overflow(now_ns=1_000_000_000)
        self.assertTrue(latch.active(now_ns=1_899_999_999))
        self.assertFalse(latch.active(now_ns=1_900_000_000))

    def test_another_event_extends_the_latch(self) -> None:
        latch = IfOverflowLatch(hold_seconds=0.9)
        latch.note_overflow(now_ns=1_000_000_000)
        latch.note_overflow(now_ns=1_500_000_000)
        self.assertTrue(latch.active(now_ns=2_399_999_999))
        self.assertFalse(latch.active(now_ns=2_400_000_000))

    def test_fatal_sdk_error_stays_on_fatal_path(self) -> None:
        self.assertTrue(classify_rta_read_status(-8).fatal)
        self.assertFalse(classify_rta_read_status(-8).process_trace)
        self.assertTrue(classify_rta_read_status(API_NO_ERROR).process_trace)

    def test_simulator_debug_overflow_reaches_runtime_status(self) -> None:
        source = SimulatorSource(point_count=32, simulate_if_overflow=False)
        self.assertFalse(source.get_status().if_overflow)
        source.set_if_overflow(True)
        self.assertTrue(source.get_status().if_overflow)
        service = AnalyzerService("simulator")
        service.source = source
        self.assertTrue(service.status_payload()["if_overflow"])


if __name__ == "__main__":
    unittest.main()
