"""Opt-in real SAN-90 waterfall batching regression tests."""

import os
import time
import unittest

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source


def _collect(source: San90Source, duration_s: float) -> tuple[float, set[int], set[int]]:
    before = source.get_status().sdk_frames_received
    rows: set[int] = set()
    generations: set[int] = set()
    started = time.monotonic()
    while time.monotonic() - started < duration_s:
        batch = source.read_waterfall_batch()
        if batch is not None:
            rows.add(batch.row_count)
            generations.add(batch.configuration_generation)
        time.sleep(0.001)
    elapsed = time.monotonic() - started
    return (source.get_status().sdk_frames_received - before) / elapsed, rows, generations


@unittest.skipUnless(os.getenv("SAN90_HARDWARE_TESTS") == "1", "SAN-90 hardware test is opt-in")
class San90WaterfallBatchTests(unittest.TestCase):
    def test_safe_fast_generation_reset_and_restore(self) -> None:
        source = San90Source()
        safe = AnalyzerSettings(
            mode="rta", center_frequency_hz=2.45e9, reference_level_dbm=0.0,
            attenuation_db=None, preamplifier="off", gain_strategy="low-noise",
            rbw_mode="auto", window="blackman-nuttall", detector="positive-peak",
        )
        try:
            source.connect()
            source.apply_settings(safe)
            source.start()
            safe_generation = source.get_settings_state().configuration_generation
            safe_rate, safe_rows, safe_generations = _collect(source, 2.0)
            safe_state = source.get_settings_state()
            self.assertEqual(safe_state.actual.point_count, 3328)
            self.assertAlmostEqual(safe_state.actual.rbw_hz, 60_306.091, delta=2.0)
            self.assertGreater(safe_rate, 6_800)
            self.assertEqual(safe_rows, {1})
            self.assertEqual(safe_generations, {safe_generation})

            source.apply_settings(source.get_settings_state().requested.updated(rbw_mode="manual", rbw_hz=300_000.0))
            fast_generation = source.get_settings_state().configuration_generation
            fast_rate, fast_rows, fast_generations = _collect(source, 3.0)
            fast_state = source.get_settings_state()
            metrics = source.get_waterfall_metrics()
            self.assertEqual(fast_state.actual.point_count, 832)
            self.assertAlmostEqual(fast_state.actual.rbw_hz, 241_224.365, delta=2.0)
            self.assertGreater(fast_rate, 27_000)
            self.assertEqual(fast_rows, {4})
            self.assertEqual(fast_generations, {fast_generation})
            self.assertIsNotNone(metrics)
            assert metrics is not None
            self.assertAlmostEqual(metrics.mean_traces_per_row, 127, delta=25)
            self.assertGreater(metrics.actual_rows_per_second, 220)
            self.assertGreater(metrics.actual_batches_per_second, 55)

            source.apply_settings(safe)
            restored_rate, restored_rows, restored_generations = _collect(source, 2.0)
            restored = source.get_settings_state()
            self.assertEqual(restored.actual.point_count, 3328)
            self.assertGreater(restored_rate, 6_800)
            self.assertEqual(restored_rows, {1})
            self.assertEqual(restored_generations, {restored.configuration_generation})
        finally:
            try:
                if source.get_device_info() is not None:
                    source.apply_settings(safe)
            finally:
                source.stop()
                source.disconnect()


if __name__ == "__main__":
    unittest.main()
