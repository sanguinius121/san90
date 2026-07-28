from __future__ import annotations

import asyncio
import math
import unittest

from backend.analyzer.errors import AnalyzerConfigurationError, ControlError, ControlErrorCode
from backend.analyzer.htra import RtaProfile
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.sweep_time import (
    SWEEP_TIME_MODE_VALUES,
    actual_trace_period_s,
    validate_manual_sweep_time,
    validate_sweep_time_multiple,
)
from backend.api.service import AnalyzerService


class SweepTimeMappingTests(unittest.TestCase):
    def test_sdk_enum_mapping_is_exact(self) -> None:
        self.assertEqual(
            SWEEP_TIME_MODE_VALUES,
            {
                "minimum": 0,
                "minimum-x2": 1,
                "minimum-x4": 2,
                "minimum-x10": 3,
                "minimum-x20": 4,
                "minimum-x50": 5,
                "custom-multiple": 6,
                "manual": 7,
            },
        )

    def test_profile_mapping_only_changes_sweep_fields(self) -> None:
        profile = RtaProfile()
        profile.CenterFreq_Hz = 2.45e9
        profile.RBW_Hz = 60_000
        profile.Window = 4
        requested = SimulatorSource().get_settings_state().requested

        San90Source._configure_sweep_time_profile(
            profile,
            requested.updated(sweep_time_mode="custom-multiple", sweep_time_multiple=8),
        )
        self.assertEqual(profile.SweepTimeMode, 6)
        self.assertEqual(profile.SweepTime, 8)
        self.assertEqual(profile.CenterFreq_Hz, 2.45e9)
        self.assertEqual(profile.RBW_Hz, 60_000)
        self.assertEqual(profile.Window, 4)

        San90Source._configure_sweep_time_profile(
            profile,
            requested.updated(sweep_time_mode="manual", sweep_time_s=.004),
        )
        self.assertEqual(profile.SweepTimeMode, 7)
        self.assertEqual(profile.SweepTime, .004)

    def test_actual_period_uses_packet_acquisition_time_and_frame_count(self) -> None:
        self.assertAlmostEqual(actual_trace_period_s(.032768, 1000) or 0, 32.768e-6)
        self.assertIsNone(actual_trace_period_s(0, 100))
        self.assertIsNone(actual_trace_period_s(math.nan, 100))
        self.assertIsNone(actual_trace_period_s(1, 0))

    def test_validated_application_bounds(self) -> None:
        self.assertEqual(validate_sweep_time_multiple(1), 1)
        self.assertEqual(validate_sweep_time_multiple(100), 100)
        self.assertEqual(validate_manual_sweep_time(1e-6), 1e-6)
        self.assertEqual(validate_manual_sweep_time(.01), .01)
        for value in (0, -1, math.nan, math.inf, 101):
            with self.assertRaises(AnalyzerConfigurationError):
                validate_sweep_time_multiple(value)
        for value in (0, -1, math.nan, math.inf, 1.1e-2):
            with self.assertRaises(AnalyzerConfigurationError):
                validate_manual_sweep_time(value)


class SweepTimeSimulatorTests(unittest.TestCase):
    def test_modes_custom_manual_and_requested_actual_separation(self) -> None:
        source = SimulatorSource(frame_rate_hz=1000)
        source.connect()
        try:
            requested = source.get_settings_state().requested
            source.apply_settings(requested.updated(sweep_time_mode="minimum-x10"))
            state = source.get_settings_state()
            self.assertEqual(state.actual.sweep_time_mode, "minimum-x10")
            self.assertAlmostEqual(state.actual.sweep_time_s or 0, .01)

            source.apply_settings(
                state.requested.updated(sweep_time_mode="custom-multiple", sweep_time_multiple=3)
            )
            state = source.get_settings_state()
            self.assertEqual(state.actual.sweep_time_multiple, 3)
            self.assertAlmostEqual(state.actual.sweep_time_s or 0, .003)

            source.apply_settings(
                state.requested.updated(sweep_time_mode="manual", sweep_time_s=.0015)
            )
            state = source.get_settings_state()
            self.assertAlmostEqual(state.requested.sweep_time_s or 0, .0015)
            self.assertAlmostEqual(state.actual.sweep_time_s or 0, .0015)
        finally:
            source.disconnect()

    def test_service_locks_sweep_time_controls(self) -> None:
        async def run() -> None:
            service = AnalyzerService("simulator")
            service.source = SimulatorSource(frame_rate_hz=1000)
            service.source.connect()
            try:
                with self.assertRaises(ControlError) as raised:
                    await service.apply_control(
                        sweep_time_mode="custom-multiple",
                        sweep_time_multiple=8,
                    )
                self.assertEqual(raised.exception.code, ControlErrorCode.UNSUPPORTED_SETTING)
                self.assertEqual(
                    service.source.get_settings_state().requested.sweep_time_mode,
                    "minimum",
                )
            finally:
                service.source.disconnect()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
