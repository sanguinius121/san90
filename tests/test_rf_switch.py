import os
import asyncio
import json
import time
import unittest
from unittest.mock import patch

from backend.analyzer.simulator import SimulatorSource
from backend.hardware.rf_switch.errors import RfSwitchReadbackMismatch, RfSwitchUnavailable
from backend.hardware.rf_switch.ft232h_switch import CONTROL_MASK, Ft232hRfSwitch, address_to_gpio_value, gpio_value_to_address
from backend.hardware.rf_switch.manager import RfSwitchManager
from backend.hardware.rf_switch.models import PATH_TO_ADDRESS, RfPath, RfSwitchConnectionState, RfSwitchVerification
from backend.hardware.rf_switch.simulator import SimulatorRfSwitch


def wait_for(predicate, timeout: float = 0.6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class FakeController:
    def __init__(self) -> None:
        self.direction = None
        self.value = 0
        self.writes = []
        self.closed = False

    def configure(self, _url, *, direction, initial) -> None:
        self.direction = direction
        self.value = initial

    def write(self, value) -> None:
        self.value = value
        self.writes.append(value)

    def read(self) -> int:
        return self.value

    def close(self) -> None:
        self.closed = True


class TrackingAbsentSwitch(SimulatorRfSwitch):
    def __init__(self) -> None:
        super().__init__()
        self.present = False
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class RfSwitchMappingTests(unittest.TestCase):
    def test_all_paths_map_sequentially_and_rf2_has_ad4_as_lsb(self) -> None:
        self.assertEqual([PATH_TO_ADDRESS[path] for path in RfPath], list(range(8)))
        self.assertEqual(PATH_TO_ADDRESS[RfPath.RF2_AUXILIARY], 0b001)

    def test_address_encoding_and_readback_mask(self) -> None:
        self.assertEqual(address_to_gpio_value(0), 0x00)
        self.assertEqual(address_to_gpio_value(7), 0x70)
        self.assertEqual(gpio_value_to_address(0b10001111), 0)
        self.assertEqual(gpio_value_to_address(0b11111111), 7)
        for invalid in (-1, 8, 1.5):
            with self.assertRaises(ValueError):
                address_to_gpio_value(invalid)  # type: ignore[arg-type]

    def test_ft232h_uses_only_control_mask_atomic_write_and_shutdown_rf8(self) -> None:
        fake = FakeController()
        cache_flushes = []
        switch = Ft232hRfSwitch(settle_s=0, controller_factory=lambda: fake, cache_flusher=lambda: cache_flushes.append(True))
        switch.open()
        self.assertEqual(cache_flushes, [True])
        self.assertEqual(fake.direction, CONTROL_MASK)
        switch.set_path(RfPath.RF2_AUXILIARY)
        self.assertEqual(fake.writes[-1], 0x10)
        self.assertEqual(switch.get_path(), RfPath.RF2_AUXILIARY)
        switch.close()
        self.assertEqual(fake.writes[-1], 0x70)
        self.assertTrue(fake.closed)
        switch.open()
        self.assertEqual(cache_flushes, [True, True])
        switch.close()


class RfSwitchReconnectTests(unittest.TestCase):
    def manager(self, switch: SimulatorRfSwitch) -> RfSwitchManager:
        return RfSwitchManager(switch, reconnect_interval_s=0.05)

    def test_simulator_starts_rf8_and_supports_every_path(self) -> None:
        switch = SimulatorRfSwitch()
        manager = self.manager(switch)
        try:
            status = manager.start()
            self.assertEqual(status.connection_state, RfSwitchConnectionState.AVAILABLE)
            self.assertEqual(status.requested_path, RfPath.RF8_WIDEBAND_ANTENNA)
            for path in RfPath:
                status = manager.set_path(path)
                self.assertEqual(status.reported_path, path)
                self.assertEqual(status.raw_address, PATH_TO_ADDRESS[path])
        finally:
            manager.stop()

    def test_unavailable_at_startup_then_automatically_connects(self) -> None:
        switch = SimulatorRfSwitch()
        switch.present = False
        manager = self.manager(switch)
        try:
            status = manager.start()
            self.assertEqual(status.connection_state, RfSwitchConnectionState.RECONNECTING)
            self.assertFalse(status.hardware_present)
            self.assertIsNone(status.requested_path)
            switch.present = True
            status = wait_for(lambda: manager.status() if manager.status().available else None)
            self.assertEqual(status.reported_path, RfPath.RF8_WIDEBAND_ANTENNA)
            self.assertEqual(status.raw_gpio_value, 0x70)
            self.assertEqual(status.verification, RfSwitchVerification.VERIFIED)
            self.assertGreaterEqual(status.reconnect_attempts, 1)
        finally:
            manager.stop()

    def test_disconnect_discards_manual_path_and_reconnect_forces_rf8(self) -> None:
        switch = SimulatorRfSwitch()
        manager = self.manager(switch)
        try:
            manager.start()
            manager.set_path("rf1")
            switch.present = False
            disconnected = wait_for(lambda: manager.status() if not manager.status().connected else None)
            self.assertFalse(disconnected.hardware_present)
            self.assertIsNone(disconnected.requested_path)
            self.assertIsNone(disconnected.reported_path)
            self.assertIsNone(disconnected.raw_gpio_value)
            self.assertEqual(disconnected.verification, RfSwitchVerification.UNAVAILABLE)
            switch.present = True
            reconnected = wait_for(lambda: manager.status() if manager.status().available else None)
            self.assertEqual(reconnected.requested_path, RfPath.RF8_WIDEBAND_ANTENNA)
            self.assertEqual(reconnected.reported_path, RfPath.RF8_WIDEBAND_ANTENNA)
            self.assertNotEqual(reconnected.reported_path, RfPath.RF1_DUAL_BAND_LNA)
        finally:
            manager.stop()

    def test_powered_transport_failure_reports_only_expected_unverified_rf8(self) -> None:
        switch = SimulatorRfSwitch()
        manager = self.manager(switch)
        try:
            manager.start()
            manager.set_path("rf4")
            switch.read_error = "PyFtdi transport stopped"
            status = wait_for(lambda: manager.status() if not manager.status().connected else None)
            self.assertTrue(status.hardware_present)
            self.assertIsNone(status.requested_path)
            self.assertIsNone(status.reported_path)
            self.assertEqual(status.expected_fail_safe_path, RfPath.RF8_WIDEBAND_ANTENNA)
            self.assertNotEqual(status.verification, RfSwitchVerification.VERIFIED)
        finally:
            manager.stop()

    def test_port_change_is_rejected_without_queueing_while_unavailable(self) -> None:
        switch = SimulatorRfSwitch()
        switch.present = False
        manager = self.manager(switch)
        try:
            manager.start()
            with self.assertRaisesRegex(RfSwitchUnavailable, "not connected") as raised:
                manager.set_path("rf2")
            self.assertEqual(raised.exception.code, "rf_switch_unavailable")
            self.assertEqual(raised.exception.http_status, 503)
            self.assertIsNone(manager.status().requested_path)
        finally:
            manager.stop()

    def test_unavailable_api_error_is_structured(self) -> None:
        from backend.main import rf_switch_error_handler

        response = asyncio.run(rf_switch_error_handler(None, RfSwitchUnavailable("The FT232H RF switch is not connected.")))  # type: ignore[arg-type]
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body), {
            "detail": {
                "code": "rf_switch_unavailable",
                "message": "The FT232H RF switch is not connected.",
            }
        })

    def test_failed_rf8_readback_after_reconnect_never_enables_controls(self) -> None:
        switch = SimulatorRfSwitch()
        switch.present = False
        manager = self.manager(switch)
        try:
            manager.start()
            switch.readback_override_address = 0
            switch.present = True
            status = wait_for(lambda: manager.status() if manager.status().verification is RfSwitchVerification.MISMATCH else None)
            self.assertFalse(status.available)
            self.assertNotEqual(status.connection_state, RfSwitchConnectionState.AVAILABLE)
            self.assertIsNone(status.requested_path)
        finally:
            manager.stop()

    def test_repeated_reconnect_attempts_release_every_failed_resource(self) -> None:
        created: list[TrackingAbsentSwitch] = []

        def factory() -> TrackingAbsentSwitch:
            switch = TrackingAbsentSwitch()
            created.append(switch)
            return switch

        manager = RfSwitchManager(switch_factory=factory, reconnect_interval_s=0.05)
        try:
            manager.start()
            wait_for(lambda: len(created) >= 4)
            self.assertTrue(all(switch.close_calls == 1 for switch in created))
            self.assertGreaterEqual(manager.status().reconnect_attempts, 3)
        finally:
            manager.stop()
        self.assertTrue(all(switch.close_calls == 1 for switch in created))

    def test_clean_shutdown_while_reconnect_worker_is_active(self) -> None:
        switch = SimulatorRfSwitch()
        switch.present = False
        manager = self.manager(switch)
        manager.start()
        started = time.monotonic()
        manager.stop()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertIsNone(manager._worker)

    def test_analyzer_acquisition_continues_during_rf_disconnect(self) -> None:
        analyzer = SimulatorSource()
        switch = SimulatorRfSwitch()
        manager = self.manager(switch)
        analyzer.connect()
        analyzer.start()
        try:
            manager.start()
            before = analyzer.get_status().sdk_frames_received
            switch.present = False
            wait_for(lambda: not manager.status().connected)
            time.sleep(0.08)
            after = analyzer.get_status().sdk_frames_received
            self.assertTrue(analyzer.get_status().acquisition_running)
            self.assertGreater(after, before)
        finally:
            manager.stop()
            analyzer.stop()
            analyzer.disconnect()

    def test_frequency_and_rbw_changes_never_change_rf_path(self) -> None:
        switch = SimulatorRfSwitch()
        manager = self.manager(switch)
        analyzer = SimulatorSource()
        try:
            manager.start()
            manager.set_path("rf3")
            analyzer.connect()
            analyzer.apply_settings(analyzer.get_settings().updated(center_frequency_hz=5.8e9))
            analyzer.apply_settings(analyzer.get_settings().updated(rbw_mode="manual", rbw_hz=300_000))
            self.assertEqual(manager.status().reported_path, RfPath.RF3_AUXILIARY)
        finally:
            manager.stop()
            analyzer.disconnect()

    def test_disabled_configuration_is_unavailable(self) -> None:
        with patch.dict(os.environ, {"SAN90_RF_SWITCH_ENABLED": "false"}, clear=True):
            manager = RfSwitchManager()
            status = manager.start()
            self.assertEqual(status.connection_state, RfSwitchConnectionState.DISABLED)
            self.assertIsNone(status.requested_path)
            with self.assertRaises(RfSwitchUnavailable):
                manager.set_path("rf1")

    def test_physical_ft232h_backend_is_enabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            manager = RfSwitchManager()
            self.assertTrue(manager.enabled)
            self.assertEqual(manager.backend, "ft232h")
            self.assertEqual(manager.status().connection_state, RfSwitchConnectionState.DISCONNECTED)


if __name__ == "__main__":
    unittest.main()
