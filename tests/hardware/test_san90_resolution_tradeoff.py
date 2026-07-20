"""Opt-in measured resolution-tradeoff validation against a connected SAN-90."""

from __future__ import annotations

import os
import time
import unittest

from backend.analyzer.models import AnalyzerSettings, SpectrumFrame, SpectrumTemporalFrame
from backend.analyzer.san90 import San90Source
from backend.analyzer.tradeoff import SAN90_RESOLUTION_TRADEOFF_STEPS, match_actual_tradeoff_step


def _frame_for_generation(source: San90Source, generation: int, timeout_s: float = 2.0) -> SpectrumFrame:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = source.read_frame()
        if frame is not None and frame.configuration_generation == generation:
            return frame
        time.sleep(0.005)
    raise AssertionError(f"No frame arrived for generation {generation}")


def _temporal_for_generation(source: San90Source, generation: int, timeout_s: float = 2.0) -> SpectrumTemporalFrame:
    deadline=time.monotonic()+timeout_s
    while time.monotonic()<deadline:
        frame=source.read_spectrum_temporal()
        if frame is not None and frame.generation==generation:
            return frame
        time.sleep(.001)
    raise AssertionError(f"No temporal spectrum arrived for generation {generation}")


@unittest.skipUnless(os.getenv("SAN90_HARDWARE_TESTS") == "1", "SAN-90 hardware test is opt-in")
class San90ResolutionTradeoffTests(unittest.TestCase):
    def test_all_steps_safe_restore_and_immediate_reopen(self) -> None:
        safe = AnalyzerSettings(
            mode="rta",
            center_frequency_hz=2.45e9,
            rbw_mode="auto",
            rbw_hz=None,
            reference_level_dbm=0.0,
            attenuation_db=None,
            preamplifier="off",
            gain_strategy="low-noise",
            window="blackman-nuttall",
            detector="positive-peak",
        )
        source = San90Source()
        try:
            source.connect()
            source.apply_settings(safe)
            source.start()
            for expected in SAN90_RESOLUTION_TRADEOFF_STEPS:
                requested = source.get_settings_state().requested.updated(
                    rbw_mode="manual", rbw_hz=expected.requested_rbw_hz
                )
                source.apply_settings(requested)
                state = source.get_settings_state()
                frame = _frame_for_generation(source, state.configuration_generation)
                temporal = _temporal_for_generation(source,state.configuration_generation)
                actual = state.actual
                matched = match_actual_tradeoff_step(
                    SAN90_RESOLUTION_TRADEOFF_STEPS,
                    actual_rbw_hz=actual.rbw_hz,
                    point_count=actual.point_count,
                    fft_size=actual.fft_size,
                )
                self.assertIsNotNone(matched)
                self.assertEqual(matched.index, expected.index)  # type: ignore[union-attr]
                self.assertEqual(frame.point_count, expected.point_count)
                self.assertEqual(temporal.point_count,expected.point_count)
                self.assertGreater(temporal.traces_integrated,0)
                self.assertEqual(temporal.latest_trace_float32.size,expected.point_count)
                self.assertEqual(temporal.interval_max_trace_float32.size,expected.point_count)
                self.assertEqual(actual.fft_size, expected.fft_size)
                metrics = source.get_waterfall_metrics()
                self.assertIsNotNone(metrics)
                self.assertEqual(metrics.rows_per_batch, expected.waterfall_rows_per_batch)  # type: ignore[union-attr]
                self.assertAlmostEqual(metrics.target_rows_per_second, expected.waterfall_rows_per_second)  # type: ignore[union-attr]

            source.apply_settings(safe)
            safe_state = source.get_settings_state()
            _frame_for_generation(source, safe_state.configuration_generation)
            _temporal_for_generation(source,safe_state.configuration_generation)
            self.assertEqual(safe_state.actual.rbw_mode, "auto")
            self.assertEqual(safe_state.actual.point_count, 3328)
        finally:
            source.stop()
            source.disconnect()

        reopened = San90Source()
        try:
            reopened.connect()
            reopened.apply_settings(safe)
            reopened.start()
            state = reopened.get_settings_state()
            _frame_for_generation(reopened, state.configuration_generation)
            self.assertEqual(state.actual.rbw_mode, "auto")
        finally:
            reopened.stop()
            reopened.disconnect()


if __name__ == "__main__":
    unittest.main()
