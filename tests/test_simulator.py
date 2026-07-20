from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

import numpy as np

from backend.analyzer.errors import AnalyzerConfigurationError, AnalyzerStateError
from backend.analyzer.factory import create_analyzer_source
from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.waterfall import WaterfallRateConfig
from backend.analyzer.tradeoff import SAN90_RESOLUTION_TRADEOFF_STEPS


class SimulatorSourceTests(unittest.TestCase):
    def test_generates_contiguous_float32_frames_and_stops(self) -> None:
        source = SimulatorSource(point_count=128, frame_rate_hz=50, seed=4)
        source.connect()
        source.start()
        deadline = time.monotonic() + 1.0
        frame = None
        while frame is None and time.monotonic() < deadline:
            frame = source.read_frame()
            time.sleep(0.005)
        source.disconnect()
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.point_count, 128)
        self.assertEqual(frame.values.dtype, np.float32)
        self.assertTrue(frame.values.flags.c_contiguous)
        self.assertFalse(source.get_status().connected)
        self.assertFalse(source.get_status().acquisition_running)

    def test_start_requires_connection(self) -> None:
        with self.assertRaises(AnalyzerStateError):
            SimulatorSource().start()

    def test_invalid_settings_are_rejected(self) -> None:
        source = SimulatorSource()
        source.connect()
        with self.assertRaises(AnalyzerConfigurationError):
            source.apply_settings(AnalyzerSettings(span_hz=-1))
        source.disconnect()

    def test_factory_defaults_to_simulator(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(create_analyzer_source(), SimulatorSource)

    def test_factory_switches_to_san90_without_changing_simulator_default(self) -> None:
        sentinel = object()
        with patch("backend.analyzer.san90.San90Source", return_value=sentinel) as constructor:
            self.assertIs(create_analyzer_source("san90"), sentinel)
            constructor.assert_called_once_with()
        self.assertIsInstance(create_analyzer_source("simulator"), SimulatorSource)

    def test_factory_rejects_unknown_source(self) -> None:
        with self.assertRaises(AnalyzerConfigurationError):
            create_analyzer_source("unknown")
        with patch.dict(os.environ, {"ANALYZER_SOURCE": "simulator"}):
            self.assertIsInstance(create_analyzer_source(), SimulatorSource)

    def test_emits_four_row_240_hz_batches(self) -> None:
        source = SimulatorSource(point_count=128, seed=7)
        source.configure_waterfall(WaterfallRateConfig(240.0, 60.0, 4))
        source.connect()
        source.start()
        deadline = time.monotonic() + 1.0
        batch = None
        while batch is None and time.monotonic() < deadline:
            batch = source.read_waterfall_batch()
            time.sleep(.002)
        source.disconnect()
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.row_count, 4)
        self.assertEqual(batch.point_count, 128)
        self.assertEqual(batch.values.shape, (4, 128))
        self.assertEqual(batch.nominal_row_period_ns, 4_166_667)

    def test_extreme_3328_to_26_to_3328_generation_transitions(self) -> None:
        source = SimulatorSource(seed=9)
        source.connect(); source.start()
        try:
            generations=[]
            for step in (SAN90_RESOLUTION_TRADEOFF_STEPS[0],SAN90_RESOLUTION_TRADEOFF_STEPS[7]):
                source.apply_settings(source.get_settings_state().requested.updated(rbw_mode="manual",rbw_hz=step.requested_rbw_hz))
                source.configure_waterfall(WaterfallRateConfig(step.waterfall_rows_per_second,60,step.waterfall_rows_per_batch))
                state=source.get_settings_state();generations.append(state.configuration_generation)
                deadline=time.monotonic()+1.0;temporal=None;batch=None
                while time.monotonic()<deadline and (temporal is None or batch is None):
                    temporal=temporal or source.read_spectrum_temporal();batch=batch or source.read_waterfall_batch();time.sleep(.001)
                self.assertIsNotNone(temporal);self.assertIsNotNone(batch)
                self.assertEqual((temporal.point_count,temporal.generation),(step.point_count,state.configuration_generation))
                self.assertEqual((batch.point_count,batch.configuration_generation),(step.point_count,state.configuration_generation))
            self.assertGreater(generations[1],generations[0])
        finally:
            source.disconnect()


if __name__ == "__main__":
    unittest.main()
