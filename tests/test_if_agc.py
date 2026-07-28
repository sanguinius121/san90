from __future__ import annotations

import asyncio
import ctypes as ct
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.analyzer.errors import AnalyzerConfigurationError
from backend.analyzer.htra import MeasAuxInfo, RtaProfile
from backend.analyzer.if_agc import validate_if_agc_period, validate_if_agc_target
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.api.service import AnalyzerService


class IfAgcValidationTests(unittest.TestCase):
    def test_target_range_and_period_modes_preserve_exact_values(self) -> None:
        self.assertEqual([validate_if_agc_target(value) for value in (-30, -9.5, 0)], [-30, -9.5, 0])
        self.assertEqual([validate_if_agc_period(value) for value in (-1, -0.25, 0, 1, 2, 2_147_483)], [-1, -0.25, 0, 1, 2, 2_147_483])
        for invalid in (-31, 1, math.nan, math.inf, -math.inf):
            with self.subTest(target=invalid), self.assertRaises(AnalyzerConfigurationError):
                validate_if_agc_target(invalid)
        for invalid in (-1.1, 2_147_484, math.nan, math.inf, -math.inf):
            with self.subTest(period=invalid), self.assertRaises(AnalyzerConfigurationError):
                validate_if_agc_period(invalid)

    def test_exact_sdk_fields_and_in_out_readbacks_preserve_unrelated_profile_values(self) -> None:
        source = San90Source()
        source._device = ct.c_void_p(123)
        profile = RtaProfile()
        profile.CenterFreq_Hz = 2.45e9
        profile.RefLevel_dBm = -10
        profile.Atten = 12
        requested = AnalyzerSettings(
            if_agc_enabled=True,
            if_agc_target_dbfs=-9.5,
            if_agc_period_s=2.0,
        )

        def target_readback(_device, pointer) -> int:
            self.assertEqual(pointer._obj.value, -9.5)
            pointer._obj.value = -9.25
            return 0

        def period_readback(_device, pointer) -> int:
            self.assertEqual(pointer._obj.value, 2.0)
            pointer._obj.value = 2.0
            return 0

        with patch.object(source._api.lib, "Device_SetIFAGCTarget", side_effect=target_readback) as target_call, patch.object(
            source._api.lib,
            "Device_SetIFAGCPeriod",
            side_effect=period_readback,
        ) as period_call:
            actual_target, actual_period = source._configure_if_agc_on_owner(profile, requested)

        self.assertEqual(profile.EnableIFAGC, 1)
        self.assertEqual((profile.CenterFreq_Hz, profile.RefLevel_dBm, profile.Atten), (2.45e9, -10, 12))
        self.assertEqual((actual_target, actual_period), (-9.25, 2.0))
        target_call.assert_called_once()
        period_call.assert_called_once()

    def test_runtime_gain_is_sampled_read_only_and_missing_state_is_unavailable(self) -> None:
        source = San90Source()
        auxiliary = MeasAuxInfo()
        auxiliary.IFAGCGain = -6.5
        source._update_if_agc_gain_from_auxiliary(auxiliary, 1_000_000_000)
        self.assertEqual(source._if_agc_gain_db, -6.5)
        auxiliary.IFAGCGain = 4.0
        source._update_if_agc_gain_from_auxiliary(auxiliary, 1_050_000_000)
        self.assertEqual(source._if_agc_gain_db, -6.5)
        source._update_if_agc_gain_from_auxiliary(auxiliary, 1_100_000_000)
        self.assertEqual(source._if_agc_gain_db, 4.0)
        auxiliary.IFAGCGain = math.nan
        source._update_if_agc_gain_from_auxiliary(auxiliary, 1_200_000_000)
        self.assertIsNone(source._if_agc_gain_db)

        simulator = SimulatorSource()
        simulator.set_if_agc_gain(None)
        self.assertIsNone(simulator.get_settings_state().actual.if_agc_gain_db)


class IfAgcServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_changes_preserve_unrelated_settings_and_if_overflow_latch(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {"AI_DETECTION_SUB_ENABLED": "false"},
            clear=True,
        ):
            service = AnalyzerService(
                "simulator",
                frequency_scan_config_path=Path(directory) / "frequency-scan.json",
            )
            await service.start()
            try:
                source = service.source
                self.assertIsInstance(source, SimulatorSource)
                source.set_if_overflow(True)
                before = source.get_settings_state()
                result = await service.apply_control(
                    if_agc_enabled=True,
                    if_agc_target_dbfs=-20.0,
                    if_agc_period_s=-1.0,
                )
                actual = result["actual"]
                self.assertTrue(actual["if_agc_enabled"])
                self.assertEqual(actual["if_agc_target_dbfs"], -20.0)
                self.assertEqual(actual["if_agc_period_s"], -1.0)
                self.assertEqual(actual["center_frequency_hz"], before.actual.center_frequency_hz)
                self.assertEqual(actual["reference_level_dbm"], before.actual.reference_level_dbm)
                self.assertTrue(service.status_payload()["if_overflow"])
            finally:
                await service.stop(disconnect=True)

    async def test_each_period_mode_is_accepted_without_multiple_scan_loops(self) -> None:
        source = SimulatorSource()
        source.connect()
        try:
            for period in (-1.0, 0.0, 1.0, 2.0):
                before = source.get_settings()
                source.apply_settings(replace(before, if_agc_period_s=period))
                state = source.get_settings_state()
                self.assertEqual(state.requested.if_agc_period_s, period)
                self.assertEqual(state.actual.if_agc_period_s, period)
        finally:
            source.disconnect()


if __name__ == "__main__":
    unittest.main()
