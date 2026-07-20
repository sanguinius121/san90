from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from backend.analyzer.models import AnalyzerSettings, DeviceInfo, SpectrumFrame
from backend.tools.inspect_san90_frame import inspect_frame
from backend.tools.test_san90_acquisition import save_first_frame


class SavedFrameTests(unittest.TestCase):
    def test_save_and_inspect_round_trip(self) -> None:
        values = np.array([-90.0, -80.0, -40.0, -70.0], dtype=np.float32)
        frame = SpectrumFrame(
            sequence=12,
            timestamp_ns=123456789,
            values=values,
            point_count=4,
            start_frequency_hz=100.0,
            center_frequency_hz=150.0,
            stop_frequency_hz=200.0,
            span_hz=100.0,
            rbw_hz=25.0,
            vbw_hz=None,
            reference_level_dbm=0.0,
            sweep_time_s=None,
        )
        device = DeviceInfo(source="san90", model="SAN-90", serial="test", model_code=67)
        with tempfile.TemporaryDirectory(prefix="san90-frame-test-") as temporary:
            saved = save_first_frame(
                Path(temporary) / "first-frame",
                frame,
                device,
                AnalyzerSettings(mode="rta"),
            )
            summary = inspect_frame(saved)
        self.assertEqual(summary.shape, (4,))
        self.assertEqual(summary.dtype, "float32")
        self.assertEqual(summary.finite_count, 4)
        self.assertEqual(summary.strongest_bin_index, 2)
        self.assertAlmostEqual(summary.strongest_bin_frequency_hz, 150.0)
        self.assertAlmostEqual(summary.strongest_bin_amplitude_dbm, -40.0)

    def test_inspector_rejects_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="san90-frame-test-") as temporary:
            path = Path(temporary) / "invalid.npz"
            np.savez(path, trace_dbm=np.array([-90.0], dtype=np.float32))
            with self.assertRaisesRegex(ValueError, "Missing required"):
                inspect_frame(path)


if __name__ == "__main__":
    unittest.main()
