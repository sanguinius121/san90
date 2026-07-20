"""Opt-in SAN-90 lifecycle checks; run with SAN90_HARDWARE_TESTS=1."""

import os
import time
import unittest

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source


@unittest.skipUnless(os.getenv("SAN90_HARDWARE_TESTS") == "1", "SAN-90 hardware test is opt-in")
class San90LifecycleTests(unittest.TestCase):
    def test_stop_close_and_immediate_reopen(self) -> None:
        for _ in range(2):
            source = San90Source()
            try:
                source.connect()
                source.apply_settings(AnalyzerSettings(mode="rta", center_frequency_hz=2.45e9, reference_level_dbm=0.0, preamplifier="off"))
                source.start()
                deadline = time.monotonic() + 2.0
                while source.get_status().sdk_frames_received == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertGreater(source.get_status().sdk_frames_received, 0)
            finally:
                source.stop()
                source.disconnect()


if __name__ == "__main__":
    unittest.main()
