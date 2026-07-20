import time
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

import numpy as np

from backend.analyzer.errors import ControlError, ControlErrorCode, SdkError
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawRtaAccumulator, RawTraceMetadata
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.api.service import AnalyzerService


class ControlModelTests(unittest.TestCase):
    def test_capabilities_are_serializable_and_explicit(self) -> None:
        service = AnalyzerService("simulator")
        service.source = SimulatorSource()
        payload = service.capabilities_payload()
        self.assertIn("center_frequency_hz", payload["supported_controls"])
        self.assertEqual(payload["center_frequency_step_hz"], 1.0)
        self.assertIn("high-linearity", payload["gain_strategy_modes"])

    def test_simulator_requested_actual_and_generation(self) -> None:
        source = SimulatorSource()
        source.connect()
        before = source.get_settings_state()
        request = replace(before.requested, center_frequency_hz=2.46e9, reference_level_dbm=-20.0)
        source.apply_settings(request)
        after = source.get_settings_state()
        self.assertEqual(after.requested.center_frequency_hz, 2.46e9)
        self.assertEqual(after.actual.center_frequency_hz, 2.46e9)
        self.assertEqual(after.configuration_generation, before.configuration_generation + 1)
        source.disconnect()

    def test_sdk_enum_mapping_is_exact(self) -> None:
        from backend.analyzer.control_mapping import GAIN_STRATEGY_VALUES, PREAMPLIFIER_VALUES
        self.assertEqual(GAIN_STRATEGY_VALUES, {"low-noise": 0, "high-linearity": 1})
        self.assertEqual(PREAMPLIFIER_VALUES, {"auto": 0, "off": 1, "low": 2, "medium": 3, "high": 4})

    def test_only_current_san90_controls_are_advertised(self) -> None:
        controls = San90Source().get_capabilities().supported_controls
        self.assertEqual(controls, {
            "center_frequency_hz", "reference_level_dbm", "attenuation_db",
            "preamplifier", "gain_strategy", "rbw_hz", "rbw_mode", "window", "detector",
            "resolution_tradeoff_index",
        })
        for deferred in ("span_hz", "vbw_hz", "if_agc_enabled"):
            self.assertNotIn(deferred, controls)

    def test_rbw_window_detector_capabilities_and_mappings(self) -> None:
        from backend.analyzer.control_mapping import DETECTOR_VALUES, RBW_MODE_VALUES, WINDOW_VALUES
        capabilities = San90Source().get_capabilities()
        self.assertTrue(capabilities.supports_rbw_control)
        self.assertFalse(capabilities.rbw_is_discrete)
        self.assertFalse(capabilities.rbw_is_profile_based)
        self.assertTrue(capabilities.rbw_changes_point_count)
        self.assertIsNone(capabilities.rbw_min_hz)
        self.assertEqual(RBW_MODE_VALUES, {"manual": 0, "auto": 1})
        self.assertEqual(WINDOW_VALUES, {"flat-top": 0, "blackman-nuttall": 1, "low-sidelobe": 2, "rectangular": 3, "kaiser": 4})
        self.assertEqual(DETECTOR_VALUES, {"sample": 0, "positive-peak": 1, "average": 2, "negative-peak": 3, "rms": 6, "auto-peak": 7})

    def test_simulator_rbw_can_resize_points_and_returns_full_actual_state(self) -> None:
        source = SimulatorSource(point_count=1024)
        source.connect()
        before = source.get_settings_state()
        source.apply_settings(before.requested.updated(rbw_mode="manual", rbw_hz=300_000, window="kaiser", detector="average"))
        after = source.get_settings_state()
        self.assertEqual(after.requested.rbw_hz, 300_000)
        self.assertAlmostEqual(after.actual.rbw_hz, 241_224.365234375)
        self.assertEqual(after.actual.point_count, 832)
        self.assertEqual(after.actual.resolution_tradeoff_index, 5)
        self.assertEqual(after.actual.window, "kaiser")
        self.assertEqual(after.actual.detector, "average")
        self.assertEqual(after.configuration_generation, before.configuration_generation + 1)
        source.disconnect()

    def test_mapping_change_resets_raw_max_atomically(self) -> None:
        accumulator = RawRtaAccumulator(2)
        first = RawTraceMetadata(1, 1, 1, 1, 1, 2, 3, 2, 1, 0, RawAmplitudeMapping(.5, -100), 1)
        second = RawTraceMetadata(2, 2, 2, 2, 1, 2, 3, 2, 1, 0, RawAmplitudeMapping(1, -50), 2)
        accumulator.update(np.array([[200, 200]], np.uint8), first)
        accumulator.update(np.array([[10, 20]], np.uint8), second)
        np.testing.assert_array_equal(accumulator.interval_max_raw, [10, 20])
        np.testing.assert_allclose(accumulator.copy_interval_max_dbm(), [-40, -30])

    def test_failed_configuration_rolls_back_without_activating_a_generation(self) -> None:
        source = San90Source()
        source._connected = True
        source._running = True
        source._configuration_generation = 4
        source._sequence = 123
        previous = replace(source._settings)
        def stop(): source._running = False; source._trigger_active = False
        def start(): source._running = True; source._trigger_active = True
        with patch.object(source, "_stop_on_owner", side_effect=stop), patch.object(source, "_start_on_owner", side_effect=start), patch.object(source, "_confirm_valid_frame_on_owner"), patch.object(source, "_configure_on_owner", side_effect=[SdkError("RTA_Configuration", -11), previous]):
            with self.assertRaises(ControlError) as raised:
                source._reconfigure_on_owner(replace(previous, center_frequency_hz=2.46e9))
        self.assertEqual(raised.exception.code, ControlErrorCode.SDK_CONFIGURATION_FAILED)
        self.assertTrue(source._running)
        self.assertEqual(source._settings.center_frequency_hz, previous.center_frequency_hz)
        self.assertEqual(source._configuration_generation, 4)
        self.assertEqual(source._sequence, 123)
        self.assertEqual(source.get_reconfiguration_metrics().rollback_attempts, 1)

    def test_owner_command_timeout_is_structured(self) -> None:
        source = San90Source(command_timeout_s=.01)
        source._ensure_owner_thread()
        try:
            with self.assertRaises(ControlError) as raised:
                source._submit(lambda: time.sleep(.1), command_type="test")
            self.assertEqual(raised.exception.code, ControlErrorCode.RECONFIGURATION_TIMEOUT)
        finally:
            source._shutdown = True
            source._thread.join(timeout=1)
            source._cancel_pending_commands()


if __name__ == "__main__":
    unittest.main()
