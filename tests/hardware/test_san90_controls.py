"""Opt-in conservative SAN-90 control transactions; run with SAN90_HARDWARE_TESTS=1."""

import math
import os
import time
import unittest

from backend.analyzer.models import AnalyzerSettings, SpectrumFrame
from backend.analyzer.san90 import San90Source


def _frame_for_generation(source: San90Source, generation: int, timeout_s: float = 2.0) -> SpectrumFrame:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = source.read_frame()
        if frame is not None and frame.configuration_generation == generation:
            return frame
        time.sleep(0.01)
    raise AssertionError(f"No spectrum frame arrived for configuration generation {generation}")


@unittest.skipUnless(os.getenv("SAN90_HARDWARE_TESTS") == "1", "SAN-90 hardware test is opt-in")
class San90ControlTests(unittest.TestCase):
    def test_control_transactions_frames_calibration_and_reopen(self) -> None:
        source = San90Source()
        safe = AnalyzerSettings(
            mode="rta",
            center_frequency_hz=2.45e9,
            reference_level_dbm=0.0,
            attenuation_db=None,
            preamplifier="off",
            gain_strategy="low-noise",
        )
        try:
            source.connect()
            source.apply_settings(safe)
            source.start()
            initial = source.get_settings_state()
            _frame_for_generation(source, initial.configuration_generation)

            actual = source.apply_settings(source.get_settings_state().requested.updated(center_frequency_hz=2.46e9))
            frequency = source.get_settings_state()
            frame = _frame_for_generation(source, frequency.configuration_generation)
            self.assertAlmostEqual(actual.center_frequency_hz, 2.46e9, delta=1.0)
            self.assertEqual(frame.configuration_generation, frequency.configuration_generation)
            self.assertAlmostEqual(frame.start_frequency_hz, frequency.actual.start_frequency_hz, delta=1.0)
            self.assertAlmostEqual(frame.stop_frequency_hz, frequency.actual.stop_frequency_hz, delta=1.0)

            source.apply_settings(source.get_settings_state().requested.updated(reference_level_dbm=-10.0))
            reference = source.get_settings_state()
            _frame_for_generation(source, reference.configuration_generation)
            self.assertTrue(math.isfinite(reference.actual.scale_to_dbm or math.nan))
            self.assertTrue(math.isfinite(reference.actual.offset_to_dbm or math.nan))

            source.apply_settings(source.get_settings_state().requested.updated(attenuation_db=10))
            attenuation = source.get_settings_state()
            _frame_for_generation(source, attenuation.configuration_generation)
            self.assertFalse(attenuation.actual.attenuation_automatic)
            self.assertIsNotNone(attenuation.actual.attenuation_db)
            self.assertTrue(math.isfinite(attenuation.actual.scale_to_dbm or math.nan))
            self.assertTrue(math.isfinite(attenuation.actual.offset_to_dbm or math.nan))

            source.apply_settings(source.get_settings_state().requested.updated(preamplifier="auto"))
            preamplifier = source.get_settings_state()
            _frame_for_generation(source, preamplifier.configuration_generation)
            self.assertIn(preamplifier.actual.preamplifier, source.get_capabilities().preamplifier_modes)

            source.apply_settings(source.get_settings_state().requested.updated(gain_strategy="high-linearity"))
            gain = source.get_settings_state()
            _frame_for_generation(source, gain.configuration_generation)
            self.assertEqual(gain.actual.gain_strategy, "high-linearity")
            self.assertGreater(gain.configuration_generation, initial.configuration_generation)

            source.apply_settings(source.get_settings_state().requested.updated(rbw_mode="manual", rbw_hz=300_000.0))
            rbw = source.get_settings_state()
            rbw_frame = _frame_for_generation(source, rbw.configuration_generation)
            self.assertAlmostEqual(rbw.actual.rbw_hz, 241_224.365234375, delta=1.0)
            self.assertEqual(rbw.actual.point_count, 832)
            self.assertEqual(rbw_frame.point_count, 832)
            self.assertTrue(math.isfinite(rbw.actual.scale_to_dbm or math.nan))
            self.assertTrue(math.isfinite(rbw.actual.offset_to_dbm or math.nan))

            source.apply_settings(source.get_settings_state().requested.updated(window="flat-top"))
            window = source.get_settings_state()
            _frame_for_generation(source, window.configuration_generation)
            self.assertEqual(window.actual.window, "flat-top")

            source.apply_settings(source.get_settings_state().requested.updated(detector="average"))
            detector = source.get_settings_state()
            _frame_for_generation(source, detector.configuration_generation)
            self.assertEqual(detector.actual.detector, "average")
        finally:
            if source.get_device_info() is not None:
                source.apply_settings(safe)
            source.stop()
            source.disconnect()

        reopened = San90Source()
        try:
            reopened.connect()
            reopened.apply_settings(safe)
            reopened.start()
            generation = reopened.get_settings_state().configuration_generation
            _frame_for_generation(reopened, generation)
        finally:
            reopened.stop()
            reopened.disconnect()


if __name__ == "__main__":
    unittest.main()
