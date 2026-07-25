from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from backend.analyzer.errors import ControlError, ControlErrorCode
from backend.analyzer.simulator import SimulatorSource
from backend.api.service import AnalyzerService
from backend.frequency_scan import FrequencyScanController, FrequencyScanEntry


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


def entry(identifier: str, frequency_hz: float, *, enabled: bool = True) -> FrequencyScanEntry:
    return FrequencyScanEntry(identifier, enabled, frequency_hz, 0.5)


class FrequencyScanControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_entries_are_ordered_disabled_are_skipped_and_scan_loops(self) -> None:
        clock = AdvancingClock()
        tunes: list[float] = []

        async def tune(frequency_hz: float) -> float:
            tunes.append(frequency_hz)
            return frequency_hz

        controller = FrequencyScanController(
            tune,
            lambda: True,
            lambda: None,
            sleep=clock.sleep,
            clock=clock.monotonic,
        )
        controller.configure(
            [entry("a", 100e6), entry("disabled", 200e6, enabled=False), entry("c", 300e6)],
            minimum_frequency_hz=1e6,
            maximum_frequency_hz=1e9,
        )
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: len(tunes) >= 3)
        await controller.stop()

        self.assertEqual(tunes[:3], [100e6, 300e6, 100e6])
        self.assertEqual(controller.status_payload()["state"], "idle")

    async def test_dwell_begins_only_after_tune_readback_completes(self) -> None:
        tune_release = asyncio.Event()
        sleep_started = asyncio.Event()

        async def tune(frequency_hz: float) -> float:
            await tune_release.wait()
            return frequency_hz

        async def blocked_sleep(_: float) -> None:
            sleep_started.set()
            await asyncio.Event().wait()

        controller = FrequencyScanController(
            tune,
            lambda: True,
            lambda: None,
            sleep=blocked_sleep,
        )
        controller.configure(
            [entry("a", 100e6)],
            minimum_frequency_hz=1e6,
            maximum_frequency_hz=1e9,
        )
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: controller.status_payload()["state"] == "tuning")
        self.assertIsNone(controller.status_payload()["remaining_dwell_seconds"])
        self.assertFalse(sleep_started.is_set())

        tune_release.set()
        await wait_until(sleep_started.is_set)
        status = controller.status_payload()
        self.assertEqual(status["state"], "dwelling")
        self.assertEqual(status["verified_center_frequency_hz"], 100e6)
        self.assertIsNotNone(status["remaining_dwell_seconds"])
        await controller.stop()

    async def test_stop_cancels_dwell_and_returns_manual_idle_state(self) -> None:
        sleep_started = asyncio.Event()

        async def blocked_sleep(_: float) -> None:
            sleep_started.set()
            await asyncio.Event().wait()

        controller = FrequencyScanController(
            lambda frequency_hz: asyncio.sleep(0, result=frequency_hz),
            lambda: True,
            lambda: None,
            sleep=blocked_sleep,
        )
        controller.configure(
            [entry("a", 100e6)],
            minimum_frequency_hz=1e6,
            maximum_frequency_hz=1e9,
        )
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(sleep_started.is_set)
        await controller.stop()
        self.assertFalse(controller.running)
        self.assertEqual(controller.status_payload()["state"], "idle")
        self.assertIsNone(controller.status_payload()["active_entry_id"])

    async def test_stop_during_tune_waits_for_safe_reconfiguration_to_finish(self) -> None:
        tune_started = asyncio.Event()
        tune_release = asyncio.Event()

        async def tune(frequency_hz: float) -> float:
            tune_started.set()
            await tune_release.wait()
            return frequency_hz

        controller = FrequencyScanController(tune, lambda: True, lambda: None)
        controller.configure([entry("a", 100e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await tune_started.wait()
        stop_task = asyncio.create_task(controller.stop())
        await wait_until(lambda: controller.status_payload()["state"] == "stopping")
        self.assertFalse(stop_task.done())
        tune_release.set()
        await stop_task
        self.assertEqual(controller.status_payload()["state"], "idle")
        self.assertFalse(controller.running)

    async def test_tune_failure_and_disconnect_stop_without_dwelling_wrong_frequency(self) -> None:
        async def failed_tune(_: float) -> float:
            raise RuntimeError("tune failed")

        failed = FrequencyScanController(failed_tune, lambda: True, lambda: None)
        failed.configure([entry("a", 100e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await failed.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: failed.status_payload()["state"] == "error")
        self.assertFalse(failed.running)
        self.assertIn("tune failed", str(failed.status_payload()["last_error"]))
        self.assertIsNone(failed.status_payload()["remaining_dwell_seconds"])

        available = True
        release_sleep = asyncio.Event()

        async def controlled_sleep(_: float) -> None:
            await release_sleep.wait()

        disconnected = FrequencyScanController(
            lambda frequency_hz: asyncio.sleep(0, result=frequency_hz),
            lambda: available,
            lambda: None,
            sleep=controlled_sleep,
        )
        disconnected.configure([entry("a", 100e6)], minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await disconnected.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)
        await wait_until(lambda: disconnected.status_payload()["state"] == "dwelling")
        available = False
        release_sleep.set()
        await wait_until(lambda: disconnected.status_payload()["state"] == "error")
        self.assertIn("unavailable", str(disconnected.status_payload()["last_error"]))

    async def test_invalid_configuration_and_no_enabled_entries_are_rejected(self) -> None:
        controller = FrequencyScanController(
            lambda frequency_hz: asyncio.sleep(0, result=frequency_hz),
            lambda: True,
            lambda: None,
        )
        with self.assertRaises(ControlError):
            controller.configure(
                [FrequencyScanEntry("bad", True, float("nan"), 0.5)],
                minimum_frequency_hz=1e6,
                maximum_frequency_hz=1e9,
            )
        with self.assertRaises(ControlError):
            controller.configure(
                [FrequencyScanEntry("bad", False, 100e6, 0.1)],
                minimum_frequency_hz=1e6,
                maximum_frequency_hz=1e9,
            )
        controller.configure(
            [entry("disabled", 100e6, enabled=False)],
            minimum_frequency_hz=1e6,
            maximum_frequency_hz=1e9,
        )
        with self.assertRaisesRegex(ControlError, "enabled"):
            await controller.start(minimum_frequency_hz=1e6, maximum_frequency_hz=1e9)


class FrequencyScanServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_simulator_scan_blocks_manual_tune_and_preserves_if_overflow(self) -> None:
        with patch.dict(os.environ, {"AI_DETECTION_SUB_ENABLED": "false"}, clear=True):
            service = AnalyzerService("simulator")
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
