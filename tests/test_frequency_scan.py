from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.analyzer.errors import ControlError, ControlErrorCode
from backend.analyzer.simulator import SimulatorSource
from backend.api.service import AnalyzerService
from backend.frequency_scan import (
    DEFAULT_FREQUENCY_SCAN_ENTRIES,
    FREQUENCY_SCAN_SCHEMA_VERSION,
    FrequencyScanController,
    FrequencyScanEntry,
)


class AdvancingClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, duration: float) -> None:
        self.now += duration
        await asyncio.sleep(0)


async def wait_until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def entry(
    identifier: str,
    frequency_hz: float,
    *,
    enabled: bool = True,
    duration_ms: int = 500,
    step_hz: float = 10e6,
    display_unit: str = "MHz",
    step_unit: str = "MHz",
) -> FrequencyScanEntry:
    return FrequencyScanEntry(
        identifier,
        enabled,
        frequency_hz,
        duration_ms,
        step_hz,
        display_unit,  # type: ignore[arg-type]
        step_unit,  # type: ignore[arg-type]
    )


class FrequencyScanPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "config" / "frequency-scan.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def controller(self) -> FrequencyScanController:
        return FrequencyScanController(
            lambda frequency_hz: asyncio.sleep(0, result=frequency_hz),
            lambda: True,
            lambda: None,
            config_path=self.path,
        )

    def load(self, controller: FrequencyScanController) -> None:
        controller.load_configuration(minimum_frequency_hz=1e6, maximum_frequency_hz=9.5e9)

    def configure(self, controller: FrequencyScanController, entries: list[FrequencyScanEntry]) -> None:
        controller.configure(entries, minimum_frequency_hz=1e6, maximum_frequency_hz=9.5e9)

    def test_missing_file_creates_valid_defaults_and_complete_atomic_json(self) -> None:
        controller = self.controller()
        replace = os.replace
        with patch("backend.frequency_scan.os.replace", side_effect=replace) as atomic_replace:
            self.load(controller)

        self.assertEqual(controller.entries, DEFAULT_FREQUENCY_SCAN_ENTRIES)
        atomic_replace.assert_called_once()
        self.assertEqual(Path(atomic_replace.call_args.args[1]), self.path)
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], FREQUENCY_SCAN_SCHEMA_VERSION)
        self.assertEqual(len(document["entries"]), 6)
        self.assertEqual(document["entries"][0]["step_hz"], 10e6)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertFalse(controller.running)
        self.assertEqual(controller.status_payload()["state"], "idle")

    def test_committed_configuration_restores_order_ids_units_steps_and_not_runtime_state(self) -> None:
        first = self.controller()
        self.load(first)
        expected = [
            entry("stable-b", 2.45e9, enabled=False, duration_ms=1_500, step_hz=25e6, display_unit="GHz"),
            entry("stable-a", 900e6, duration_ms=2_000, step_hz=5e6),
        ]
        self.configure(first, expected)

        restarted = self.controller()
        self.load(restarted)
        self.assertEqual(restarted.entries, tuple(expected))
        status = restarted.status_payload()
        self.assertFalse(status["running"])
        self.assertEqual(status["state"], "idle")
        document = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("running", document)
        self.assertNotIn("active_entry_id", document)
        self.assertNotIn("last_error", document)

    def test_malformed_or_unsupported_json_falls_back_without_overwriting_file(self) -> None:
        self.path.parent.mkdir(parents=True)
        for content in ("{broken", '{"version": 99, "entries": []}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                controller = self.controller()
                self.load(controller)
                self.assertEqual(controller.entries, DEFAULT_FREQUENCY_SCAN_ENTRIES)
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)
                self.assertIn("using defaults", str(controller.status_payload()["configuration_load_warning"]))

    def test_invalid_frequency_duration_step_and_unit_are_rejected(self) -> None:
        controller = self.controller()
        invalid = (
            entry("bad", float("nan")),
            entry("bad", float("inf")),
            entry("bad", 100e6, duration_ms=100),
            entry("bad", 100e6, duration_ms=float("inf")),  # type: ignore[arg-type]
            entry("bad", 100e6, step_hz=0),
            entry("bad", 100e6, step_hz=float("nan")),
            entry("bad", 100e6, step_hz=float("inf")),
            entry("bad", 100e6, step_hz=10e9),
            entry("bad", 100e6, display_unit="kHz"),
            entry("bad", 100e6, step_unit="kHz"),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ControlError):
                self.configure(controller, [candidate])

    def test_step_values_are_independent_and_disk_failure_preserves_memory(self) -> None:
        controller = self.controller()
        self.load(controller)
        expected = [entry("a", 100e6, step_hz=5e6), entry("b", 200e6, step_hz=25e6)]
        with patch("backend.frequency_scan.os.replace", side_effect=OSError("disk full")):
            self.configure(controller, expected)
        self.assertEqual([value.step_hz for value in controller.entries], [5e6, 25e6])
        self.assertIn("disk full", str(controller.status_payload()["configuration_save_error"]))


class FrequencyScanControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_entries_are_ordered_disabled_are_skipped_and_scan_loops(self) -> None:
        clock = AdvancingClock()
        tunes: list[float] = []

        async def tune(frequency_hz: float) -> float:
            tunes.append(frequency_hz)
            return frequency_hz

        controller = FrequencyScanController(tune, lambda: True, lambda: None, sleep=clock.sleep, clock=clock.monotonic)
        controller.configure(
            [entry("a", 100e6), entry("disabled", 200e6, enabled=False), entry("c", 300e6)],
            minimum_frequency_hz=1e6,
            maximum_frequency_hz=1e9,
        )
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: len(tunes) >= 3)
        await controller.stop()
        self.assertEqual(tunes[:3], [100e6, 300e6, 100e6])

    async def test_edit_while_scanning_does_not_restart_current_dwell_and_applies_next_visit(self) -> None:
        dwell_release = asyncio.Event()
        dwell_calls = 0
        tunes: list[float] = []

        async def tune(frequency_hz: float) -> float:
            tunes.append(frequency_hz)
            return frequency_hz

        async def controlled_sleep(_: float) -> None:
            nonlocal dwell_calls
            dwell_calls += 1
            await dwell_release.wait()
            await asyncio.sleep(0)

        controller = FrequencyScanController(tune, lambda: True, lambda: None, sleep=controlled_sleep)
        controller.configure([entry("a", 100e6), entry("b", 200e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: controller.status_payload()["state"] == "dwelling")
        self.assertEqual(tunes, [100e6])

        controller.configure([entry("a", 150e6), entry("b", 250e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        self.assertEqual(tunes, [100e6])
        self.assertEqual(dwell_calls, 1)
        dwell_release.set()
        await wait_until(lambda: len(tunes) >= 3)
        await controller.stop()
        self.assertEqual(tunes[:3], [100e6, 250e6, 150e6])

    async def test_delete_active_continues_safely_and_disabling_all_stops_after_dwell(self) -> None:
        clock = AdvancingClock()
        tunes: list[float] = []

        async def tune(frequency_hz: float) -> float:
            tunes.append(frequency_hz)
            return frequency_hz

        controller = FrequencyScanController(tune, lambda: True, lambda: None, sleep=clock.sleep, clock=clock.monotonic)
        controller.configure([entry("a", 100e6), entry("b", 200e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: len(tunes) >= 1)
        controller.configure([entry("b", 200e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: 200e6 in tunes)
        controller.configure([entry("b", 200e6, enabled=False)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: not controller.running)
        self.assertEqual(controller.status_payload()["state"], "idle")

    async def test_dwell_begins_only_after_tune_readback_and_stop_during_tune_is_safe(self) -> None:
        tune_release = asyncio.Event()
        sleep_started = asyncio.Event()

        async def tune(frequency_hz: float) -> float:
            await tune_release.wait()
            return frequency_hz

        async def blocked_sleep(_: float) -> None:
            sleep_started.set()
            await asyncio.Event().wait()

        controller = FrequencyScanController(tune, lambda: True, lambda: None, sleep=blocked_sleep)
        controller.configure([entry("a", 100e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: controller.status_payload()["state"] == "tuning")
        stop_task = asyncio.create_task(controller.stop())
        await wait_until(lambda: controller.status_payload()["state"] == "stopping")
        self.assertFalse(stop_task.done())
        tune_release.set()
        await stop_task
        self.assertFalse(sleep_started.is_set())
        self.assertEqual(controller.status_payload()["state"], "idle")

    async def test_invalid_configuration_and_no_enabled_entries_are_rejected(self) -> None:
        controller = FrequencyScanController(lambda frequency_hz: asyncio.sleep(0, result=frequency_hz), lambda: True, lambda: None)
        controller.configure([entry("disabled", 100e6, enabled=False)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        with self.assertRaisesRegex(ControlError, "enabled"):
            await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)


class FrequencyScanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_scan_blocks_manual_tune_and_preserves_if_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"AI_DETECTION_SUB_ENABLED": "false"},
            clear=True,
        ):
            service = AnalyzerService(
                "simulator",
                frequency_scan_config_path=Path(directory) / "frequency-scan.json",
            )
            await service.start()
            try:
                self.assertIsInstance(service.source, SimulatorSource)
                service.source.set_if_overflow(True)
                service.configure_frequency_scan([
                    entry("a", 2.44e9),
                    entry("disabled", 2.45e9, enabled=False),
                    entry("b", 2.46e9),
                ])
                await service.start_frequency_scan()
                await wait_until(lambda: service.frequency_scan.status_payload()["state"] == "dwelling")
                self.assertTrue(service.status_payload()["if_overflow"])
                with self.assertRaises(ControlError) as caught:
                    await service.apply_control(center_frequency_hz=2.47e9)
                self.assertEqual(caught.exception.code, ControlErrorCode.DEVICE_BUSY)
                await service.stop_frequency_scan()
                self.assertEqual(service.frequency_scan.status_payload()["state"], "idle")
                await service.apply_control(center_frequency_hz=2.47e9)
                self.assertEqual(service.settings_payload()["actual"]["center_frequency_hz"], 2.47e9)
                self.assertTrue(service.status_payload()["if_overflow"])
            finally:
                await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
