from __future__ import annotations

import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.analyzer.errors import AnalyzerConfigurationError, ControlError
from backend.analyzer.htra import RtaProfile
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.vbw import (
    VBW_EXPOSED_MODES,
    VBW_FIXED_MODE,
    VBW_MANUAL_REQUEST_MAX_HZ,
    VBW_MODE_VALUES,
    validate_fixed_vbw_mode,
    validate_manual_vbw,
    validate_vbw_mode,
    verified_vbw_hz,
)
from backend.api.service import AnalyzerService


class VbwMappingTests(unittest.TestCase):
    def test_exact_sdk_enum_mapping(self) -> None:
        self.assertEqual(
            VBW_MODE_VALUES,
            {
                "manual": 0,
                "ratio-1": 1,
                "ratio-0.1": 2,
                "ratio-0.01": 3,
                "ratio-10": 4,
            },
        )
        self.assertEqual(VBW_FIXED_MODE, "ratio-0.1")
        self.assertEqual(VBW_EXPOSED_MODES, ())
        capabilities = San90Source().get_capabilities()
        self.assertNotIn("vbw_mode", capabilities.supported_controls)
        self.assertNotIn("vbw_mode", capabilities.enum_values)
        self.assertNotIn("vbw_hz", capabilities.supported_controls)
        self.assertNotIn("vbw_hz", capabilities.numeric_ranges)

    def test_profile_mapping_is_fixed_and_preserves_unrelated_fields(self) -> None:
        profile = RtaProfile()
        profile.CenterFreq_Hz = 2.45e9
        profile.RBWMode = 1
        profile.RBW_Hz = 60_306.091
        profile.VBW_Hz = 777
        profile.RefLevel_dBm = -10
        settings = AnalyzerSettings(vbw_mode=VBW_FIXED_MODE, vbw_hz=12_345.67)
        San90Source._configure_vbw_profile(profile, settings)
        self.assertEqual(profile.VBWMode, VBW_MODE_VALUES[VBW_FIXED_MODE])
        self.assertEqual(profile.VBW_Hz, 777)
        self.assertEqual(
            (profile.CenterFreq_Hz, profile.RBWMode, profile.RBW_Hz, profile.RefLevel_dBm),
            (2.45e9, 1, 60_306.091, -10),
        )
        for mode in set(VBW_MODE_VALUES) - {VBW_FIXED_MODE}:
            with self.subTest(mode=mode), self.assertRaises(AnalyzerConfigurationError):
                San90Source._configure_vbw_profile(profile, replace(settings, vbw_mode=mode))

    def test_validation_and_unavailable_readback(self) -> None:
        self.assertEqual(validate_manual_vbw(1), 1)
        self.assertEqual(validate_manual_vbw(12_345.67), 12_345.67)
        self.assertEqual(validate_manual_vbw(VBW_MANUAL_REQUEST_MAX_HZ), VBW_MANUAL_REQUEST_MAX_HZ)
        for value in (None, 0, -1, VBW_MANUAL_REQUEST_MAX_HZ + 1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(AnalyzerConfigurationError):
                validate_manual_vbw(value)
        with self.assertRaises(AnalyzerConfigurationError):
            validate_vbw_mode("auto")
        self.assertEqual(validate_fixed_vbw_mode(VBW_FIXED_MODE), VBW_FIXED_MODE)
        for mode in set(VBW_MODE_VALUES) - {VBW_FIXED_MODE}:
            with self.subTest(mode=mode), self.assertRaises(AnalyzerConfigurationError):
                validate_fixed_vbw_mode(mode)
        self.assertIsNone(verified_vbw_hz(math.nan))
        self.assertIsNone(verified_vbw_hz(0))

    def test_simulator_keeps_fixed_ratio_across_rbw_changes(self) -> None:
        source = SimulatorSource()
        before = source.get_settings_state()
        source.apply_settings(replace(before.requested, rbw_mode="manual", rbw_hz=241_224.365))
        ratio = source.get_settings_state()
        self.assertEqual(ratio.actual.vbw_mode, VBW_FIXED_MODE)
        self.assertAlmostEqual(ratio.actual.vbw_hz or 0, ratio.actual.rbw_hz * 0.1)
        for mode in set(VBW_MODE_VALUES) - {VBW_FIXED_MODE}:
            with self.subTest(mode=mode), self.assertRaises(AnalyzerConfigurationError):
                source.apply_settings(replace(ratio.requested, vbw_mode=mode))


class VbwServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rbw_change_preserves_fixed_vbw_and_if_overflow_latch(self) -> None:
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
                result = await service.apply_control(rbw_mode="manual", rbw_hz=241_224.365)
                self.assertEqual(result["actual"]["vbw_mode"], VBW_FIXED_MODE)
                self.assertAlmostEqual(
                    result["actual"]["vbw_hz"],
                    result["actual"]["rbw_hz"] * 0.1,
                )
                self.assertEqual(result["actual"]["center_frequency_hz"], before.actual.center_frequency_hz)
                self.assertNotAlmostEqual(result["actual"]["rbw_hz"], before.actual.rbw_hz, delta=1)
                self.assertEqual(result["actual"]["if_agc_enabled"], before.actual.if_agc_enabled)
                self.assertTrue(service.status_payload()["if_overflow"])
                with self.assertRaises(ControlError):
                    await service.apply_control(vbw_mode=VBW_FIXED_MODE)
            finally:
                await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
