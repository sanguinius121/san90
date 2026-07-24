from __future__ import annotations

import time
import unittest

import numpy as np

from backend.ai_stream.image_accumulator import raw_packet_to_dbm
from backend.ai_stream.power_profiles import dbm_to_gray8
from backend.analyzer.amplitude_correction import (
    corrected_amplitude_mapping,
    validate_amplitude_offset,
)
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.spectrum_temporal import NativeSpectrumTemporalAccumulator


def metadata(mapping: RawAmplitudeMapping) -> RawTraceMetadata:
    now = time.monotonic_ns()
    return RawTraceMetadata(
        sequence=2,
        device_timestamp_ns=1,
        host_timestamp_ns=2,
        receipt_monotonic_ns=now,
        start_frequency_hz=100.0,
        center_frequency_hz=150.0,
        stop_frequency_hz=200.0,
        span_hz=100.0,
        rbw_hz=10.0,
        reference_level_dbm=0.0,
        mapping=mapping,
        configuration_generation=1,
    )


class AmplitudeOffsetTests(unittest.TestCase):
    def test_offset_changes_raw_conversion_by_exactly_once(self) -> None:
        raw = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        hardware = RawAmplitudeMapping(0.5, -100.0)
        baseline = np.empty(raw.shape, dtype=np.float32)
        hardware.convert(raw, baseline)
        for offset_db in (0.0, 10.0, -10.0):
            with self.subTest(offset_db=offset_db):
                corrected = np.empty(raw.shape, dtype=np.float32)
                corrected_amplitude_mapping(hardware, offset_db).convert(raw, corrected)
                np.testing.assert_allclose(corrected, baseline + offset_db)

    def test_current_and_interval_max_receive_one_offset(self) -> None:
        raw = np.array([[10, 50], [40, 20]], dtype=np.uint8)
        hardware = RawAmplitudeMapping(1.0, -100.0)
        accumulator = NativeSpectrumTemporalAccumulator(2)
        accumulator.add_packet(raw, metadata(corrected_amplitude_mapping(hardware, 10.0)))
        frame = accumulator.flush(time.monotonic_ns())
        self.assertIsNotNone(frame)
        assert frame is not None
        np.testing.assert_array_equal(frame.latest_trace_float32, [-50.0, -70.0])
        np.testing.assert_array_equal(frame.interval_max_trace_float32, [-50.0, -40.0])

    def test_offset_update_preserves_hardware_controls_overflow_and_generation(self) -> None:
        source = SimulatorSource(seed=1, simulate_if_overflow=True)
        before = source.get_settings_state()
        self.assertTrue(source.get_status().if_overflow)

        self.assertEqual(source.apply_amplitude_offset(10.0), 10.0)
        after = source.get_settings_state()

        self.assertEqual(after.configuration_generation, before.configuration_generation)
        self.assertEqual(after.actual.reference_level_dbm, before.actual.reference_level_dbm)
        self.assertEqual(after.actual.attenuation_db, before.actual.attenuation_db)
        self.assertEqual(after.actual.amplitude_offset_db, 10.0)
        self.assertTrue(source.get_status().if_overflow)

    def test_gray8_pipeline_receives_corrected_absolute_power(self) -> None:
        raw = np.full((640, 640), 100, dtype=np.uint8)
        hardware = RawAmplitudeMapping(0.5, -120.0)
        baseline_dbm = raw_packet_to_dbm(raw, hardware)
        corrected_dbm = raw_packet_to_dbm(raw, corrected_amplitude_mapping(hardware, 10.0))
        np.testing.assert_allclose(corrected_dbm, baseline_dbm + 10.0)

        baseline_gray = dbm_to_gray8(baseline_dbm, -120.0, -20.0)
        corrected_gray = dbm_to_gray8(corrected_dbm, -120.0, -20.0)
        self.assertGreater(int(corrected_gray[0, 0]), int(baseline_gray[0, 0]))

    def test_invalid_offset_is_rejected(self) -> None:
        for value in (float("nan"), float("inf"), -100.1, 100.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_amplitude_offset(value)
