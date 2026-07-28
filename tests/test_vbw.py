from __future__ import annotations

import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.analyzer.errors import AnalyzerConfigurationError
from backend.analyzer.htra import RtaProfile
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.vbw import (
    VBW_EXPOSED_MODES,
    VBW_MANUAL_REQUEST_MAX_HZ,
    VBW_MODE_VALUES,
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
        self.assertEqual(VBW_EXPOSED_MODES, ("ratio-1", "ratio-0.1"))
        capabilities = San90Source().get_capabilities()
        self.assertEqual(capabilities.enum_values["vbw_mode"], VBW_EXPOSED_MODES)
        self.assertNotIn("vbw_hz", capabilities.supported_controls)

    def test_profile_mapping_preserves_unrelated_fields_and_manual_value(self) -> None:
        profile = RtaProfile()
        profile.CenterFreq_Hz = 2.45e9
        profile.RBWMode = 1
        profile.RBW_Hz = 60_306.091
        profile.RefLevel_dBm = -10
        settings = AnalyzerSettings(vbw_mode="manual", vbw_hz=12_345.67)
        San90Source._configure_vbw_profile(profile, settings)
        self.assertEqual(profile.VBWMode, 0)
        self.assertEqual(profile.VBW_Hz, 12_345.67)
        self.assertEqual(
            (profile.CenterFreq_Hz, profile.RBWMode, profile.RBW_Hz, profile.RefLevel_dBm),
            (2.45e9, 1, 60_306.091, -10),
        )
        for mode, value in VBW_MODE_VALUES.items():
            if mode == "manual":
                continue
            profile.VBW_Hz = 777
            San90Source._configure_vbw_profile(profile, replace(settings, vbw_mode=mode))
            self.assertEqual(profile.VBWMode, value)
            self.assertEqual(profile.VBW_Hz, 777)

    def test_validation_and_unavailable_readback(self) -> None:
        self.assertEqual(validate_manual_vbw(1), 1)
        self.assertEqual(validate_manual_vbw(12_345.67), 12_345.67)
        self.assertEqual(validate_manual_vbw(VBW_MANUAL_REQUEST_MAX_HZ), VBW_MANUAL_REQUEST_MAX_HZ)
        for value in (None, 0, -1, VBW_MANUAL_REQUEST_MAX_HZ + 1, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(AnalyzerConfigurationError):
                validate_manual_vbw(value)
        with self.assertRaises(AnalyzerConfigurationError):
            validate_vbw_mode("auto")
        self.assertIsNone(verified_vbw_hz(math.nan))
        self.assertIsNone(verified_vbw_hz(0))

    def test_simulator_ratio_uses_actual_rbw_and_manual_is_separate(self) -> None:
        source = SimulatorSource()
        before = source.get_settings_state()
        source.apply_settings(replace(before.requested, vbw_mode="ratio-0.1", vbw_hz=12_345.67))
        ratio = source.get_settings_state()
        self.assertEqual(ratio.requested.vbw_hz, 12_345.67)
        self.assertAlmostEqual(ratio.actual.vbw_hz or 0, ratio.actual.rbw_hz * 0.1)
        source.apply_settings(replace(ratio.requested, vbw_mode="manual"))
        manual = source.get_settings_state()
        self.assertEqual(manual.actual.vbw_hz, 12_345.67)


class VbwServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_vbw_change_preserves_controls_and_if_overflow_latch(self) -> None:
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
                result = await service.apply_control(vbw_mode="ratio-0.1")
                self.assertEqual(result["actual"]["vbw_mode"], "ratio-0.1")
                self.assertAlmostEqual(
                    result["actual"]["vbw_hz"],
                    result["actual"]["rbw_hz"] * 0.1,
                )
                self.assertEqual(result["actual"]["center_frequency_hz"], before.actual.center_frequency_hz)
                self.assertAlmostEqual(result["actual"]["rbw_hz"], before.actual.rbw_hz, delta=1)
                self.assertEqual(result["actual"]["if_agc_enabled"], before.actual.if_agc_enabled)
                self.assertTrue(service.status_payload()["if_overflow"])
            finally:
                await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
