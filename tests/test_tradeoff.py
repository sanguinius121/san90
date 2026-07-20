import asyncio
import unittest
from dataclasses import asdict, replace

from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.tradeoff import (
    SAN90_RESOLUTION_TRADEOFF_STEPS,
    match_actual_tradeoff_step,
    sort_and_deduplicate_steps,
    validate_tradeoff_index,
    visible_rows,
)
from backend.analyzer.waterfall import waterfall_rate_for_profile
from backend.api.service import AnalyzerService


class ResolutionTradeoffModelTests(unittest.TestCase):
    def test_steps_serialize_and_are_sorted_time_to_frequency(self) -> None:
        payload = [asdict(step) for step in SAN90_RESOLUTION_TRADEOFF_STEPS]
        self.assertEqual([item["index"] for item in payload], list(range(8)))
        self.assertEqual(payload[0]["id"], "time-0")
        self.assertEqual(payload[-1]["id"], "time-7")
        self.assertEqual([step.point_count for step in SAN90_RESOLUTION_TRADEOFF_STEPS], [26,52,104,208,416,832,1664,3328])
        self.assertEqual([step.fft_size for step in SAN90_RESOLUTION_TRADEOFF_STEPS], [32,64,128,256,512,1024,2048,4096])
        self.assertEqual([step.requested_rbw_hz for step in SAN90_RESOLUTION_TRADEOFF_STEPS], [8e6,4e6,2e6,1e6,5e5,3e5,15e4,5e4])
        self.assertTrue(all(
            step.spectrum_publish_fps == step.spectrum_render_fps == step.webgl_target_fps == 60
            for step in SAN90_RESOLUTION_TRADEOFF_STEPS
        ))
        self.assertEqual(
            [step.actual_rbw_hz for step in SAN90_RESOLUTION_TRADEOFF_STEPS],
            sorted((step.actual_rbw_hz for step in SAN90_RESOLUTION_TRADEOFF_STEPS), reverse=True),
        )

    def test_duplicate_actual_profiles_are_removed_and_reindexed(self) -> None:
        frequency = SAN90_RESOLUTION_TRADEOFF_STEPS[-1]
        duplicate = replace(frequency, id="duplicate", index=99, requested_rbw_hz=15_000.0)
        result = sort_and_deduplicate_steps((*SAN90_RESOLUTION_TRADEOFF_STEPS, duplicate))
        self.assertEqual(len(result), 8)
        self.assertEqual([step.index for step in result], list(range(8)))

    def test_index_validation_and_actual_matching(self) -> None:
        self.assertEqual(validate_tradeoff_index(SAN90_RESOLUTION_TRADEOFF_STEPS, 5).point_count, 832)
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_tradeoff_index(SAN90_RESOLUTION_TRADEOFF_STEPS, 8)
        matched = match_actual_tradeoff_step(
            SAN90_RESOLUTION_TRADEOFF_STEPS,
            actual_rbw_hz=241_224.4,
            point_count=832,
            fft_size=1024,
        )
        self.assertIsNotNone(matched)
        self.assertEqual(matched.index, 5)
        self.assertIsNone(match_actual_tradeoff_step(
            SAN90_RESOLUTION_TRADEOFF_STEPS,
            actual_rbw_hz=241_224.4,
            point_count=831,
            fft_size=1024,
        ))

    def test_step_waterfall_policy_and_fixed_visible_span(self) -> None:
        expected = [(480,8,2400)]*5 + [(240,4,1200),(120,2,600),(60,1,300)]
        for step, (rows, batch_rows, visible) in zip(SAN90_RESOLUTION_TRADEOFF_STEPS, expected):
            config = waterfall_rate_for_profile(step.actual_rbw_hz, step.point_count)
            self.assertEqual((config.rows_per_second, config.rows_per_batch), (rows, batch_rows))
            self.assertEqual(visible_rows(config.rows_per_second), visible)
            self.assertGreater(step.measured_trace_rate_hz / rows, 120)

    def test_simulator_auto_matched_and_custom_states(self) -> None:
        source = SimulatorSource()
        source.connect()
        auto = source.get_settings_state()
        self.assertEqual(auto.actual.resolution_tradeoff_state, "auto")
        self.assertIsNone(auto.actual.resolution_tradeoff_index)
        source.apply_settings(auto.requested.updated(rbw_mode="manual", rbw_hz=500_000.0))
        matched = source.get_settings_state()
        self.assertEqual((matched.actual.resolution_tradeoff_index, matched.actual.point_count), (4, 416))
        source.apply_settings(matched.requested.updated(rbw_hz=123_456.0))
        custom = source.get_settings_state()
        self.assertEqual(custom.actual.resolution_tradeoff_state, "custom")
        self.assertIsNone(custom.actual.resolution_tradeoff_index)
        source.disconnect()


class ResolutionTradeoffServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_endpoint_applies_one_generation_and_returns_readback(self) -> None:
        service = AnalyzerService("simulator")
        await service.start()
        try:
            before = service.source.get_settings_state().configuration_generation
            result = await service.apply_resolution_tradeoff(6)
            self.assertEqual((result["requested_index"], result["actual_index"]), (6, 6))
            self.assertEqual((result["point_count"], result["visible_rows"]), (1664, 600))
            self.assertEqual(result["configuration_generation"], before + 1)
            self.assertEqual(service.spectrum_fps, 60.0)
            self.assertEqual(result["spectrum_render_fps"], 60.0)
        finally:
            await service.stop(disconnect=True)

    async def test_invalid_index_is_rejected(self) -> None:
        service = AnalyzerService("simulator")
        await service.start()
        try:
            with self.assertRaisesRegex(Exception, "outside"):
                await service.apply_resolution_tradeoff(99)
        finally:
            await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
