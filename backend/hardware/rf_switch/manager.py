"""Lifecycle owner and reconnect worker for the low-rate RF switch."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import replace
from typing import Callable

from .base import RfSwitch
from .errors import RfSwitchReadbackMismatch, RfSwitchUnavailable
from .ft232h_switch import FTDI_URL, Ft232hRfSwitch, gpio_value_to_address
from .models import (
    PATH_TO_ADDRESS,
    RfPath,
    RfSwitchConnectionState,
    RfSwitchStatus,
    RfSwitchVerification,
    capabilities_payload,
    parse_rf_path,
)
from .simulator import SimulatorRfSwitch

logger = logging.getLogger("san90.rf_switch")


def _enabled(value: str | None) -> bool:
    # Physical FT232H support is the production default. An explicit false
    # value remains available for systems intentionally running without it.
    return value is None or value.strip().lower() in {"1", "true", "yes", "on"}


class RfSwitchManager:
    def __init__(
        self,
        switch: RfSwitch | None = None,
        *,
        switch_factory: Callable[[], RfSwitch] | None = None,
        reconnect_interval_s: float | None = None,
    ) -> None:
        if switch is not None and switch_factory is not None:
            raise ValueError("provide switch or switch_factory, not both")
        self.enabled = _enabled(os.getenv("SAN90_RF_SWITCH_ENABLED")) if switch is None and switch_factory is None else True
        self.backend = os.getenv("SAN90_RF_SWITCH_BACKEND", "ft232h").strip().lower() if switch is None else (
            "simulator" if isinstance(switch, SimulatorRfSwitch) else "ft232h"
        )
        self.url = os.getenv("SAN90_RF_SWITCH_URL", FTDI_URL)
        self.settle_s = float(os.getenv("SAN90_RF_SWITCH_SETTLE_MS", "5")) / 1000.0
        interval = reconnect_interval_s if reconnect_interval_s is not None else float(os.getenv("SAN90_RF_SWITCH_RECONNECT_SECONDS", "2"))
        if not 0.05 <= interval <= 300:
            raise ValueError("RF-switch reconnect interval must be between 0.05 and 300 seconds")
        self.reconnect_interval_s = interval
        configured_default = os.getenv("SAN90_RF_SWITCH_DEFAULT_PATH", "rf8")
        if configured_default.strip().lower() != "rf8":
            logger.warning("Ignoring non-failsafe SAN90_RF_SWITCH_DEFAULT_PATH=%s; session starts in RF8", configured_default)
        self._provided_switch = switch
        self._switch_factory = switch_factory
        self._switch: RfSwitch | None = switch
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        now = time.monotonic()
        self._status = RfSwitchStatus(
            connection_state=RfSwitchConnectionState.DISABLED if not self.enabled else RfSwitchConnectionState.DISCONNECTED,
            backend=self.backend if self.enabled else "disabled",
            simulated=self.backend == "simulator" and self.enabled,
            updated_at_monotonic=now,
        )

    def _create_switch(self) -> RfSwitch:
        if self._switch_factory is not None:
            return self._switch_factory()
        if self._provided_switch is not None:
            return self._provided_switch
        if self.backend == "ft232h":
            return Ft232hRfSwitch(self.url, settle_s=self.settle_s)
        if self.backend == "simulator":
            return SimulatorRfSwitch()
        raise ValueError("SAN90_RF_SWITCH_BACKEND must be 'ft232h' or 'simulator'")

    def capabilities(self) -> dict[str, object]:
        return capabilities_payload(self.enabled)

    def status(self) -> RfSwitchStatus:
        with self._lock:
            return self._status

    def refresh(self) -> RfSwitchStatus:
        """Return the worker-maintained status without touching USB."""
        return self.status()

    def _presence(self, switch: RfSwitch | None) -> bool:
        if switch is None:
            return False
        try:
            return bool(switch.is_hardware_present())
        except Exception:
            return False

    def _release_switch_locked(self, switch: RfSwitch | None) -> None:
        if switch is None:
            return
        try:
            switch.close()
        except Exception:
            logger.exception("RF-switch controller release failed")
        finally:
            self._switch = None

    def _mark_failure_locked(self, error: Exception, switch: RfSwitch | None, *, was_connected: bool) -> None:
        present = self._presence(switch)
        disconnected_at = time.time()
        self._release_switch_locked(switch)
        verification = RfSwitchVerification.MISMATCH if isinstance(error, RfSwitchReadbackMismatch) else RfSwitchVerification.UNAVAILABLE
        state = RfSwitchConnectionState.ERROR if present and verification is RfSwitchVerification.MISMATCH else RfSwitchConnectionState.RECONNECTING
        self._status = replace(
            self._status,
            connection_state=state,
            hardware_present=present,
            available=False,
            connected=False,
            requested_path=None,
            reported_path=None,
            expected_fail_safe_path=RfPath.RF8_WIDEBAND_ANTENNA if present and was_connected else None,
            raw_address=None,
            raw_gpio_value=None,
            readback_matches_request=False,
            verification=verification,
            last_error=str(error),
            last_disconnected_at=disconnected_at,
            updated_at_monotonic=time.monotonic(),
        )
        logger.warning(
            "RF switch disconnected hardware_present=%s state=%s error=%s",
            present,
            state.value,
            error,
        )

    def _verify_path_locked(self, path: RfPath) -> RfSwitchStatus:
        switch = self._switch
        if switch is None:
            raise RfSwitchUnavailable("The FT232H RF switch is not connected.")
        logger.info(
            "RF path change requested path=%s channel=RF%d address=%s",
            path.value,
            PATH_TO_ADDRESS[path] + 1,
            f"{PATH_TO_ADDRESS[path]:03b}",
        )
        switch.set_path(path)
        reported = switch.get_path()
        raw = switch.raw_gpio_value
        address = None if raw is None else gpio_value_to_address(raw)
        if reported is not path or address != PATH_TO_ADDRESS[path]:
            raise RfSwitchReadbackMismatch(
                f"requested {path.value}, reported {reported.value}, raw={raw!r}"
            )
        now_wall = time.time()
        self._status = replace(
            self._status,
            connection_state=RfSwitchConnectionState.AVAILABLE,
            hardware_present=True,
            available=True,
            connected=True,
            requested_path=path,
            reported_path=reported,
            expected_fail_safe_path=None,
            raw_address=address,
            raw_gpio_value=raw,
            readback_matches_request=True,
            verification=RfSwitchVerification.VERIFIED,
            last_error=None,
            last_connected_at=now_wall,
            updated_at_monotonic=time.monotonic(),
        )
        logger.info("RF path changed successfully path=%s address=%s raw=0x%02x", path.value, f"{address:03b}", raw)
        return self._status

    def _connect_locked(self, *, initial: bool) -> RfSwitchStatus:
        attempts = self._status.reconnect_attempts + (0 if initial else 1)
        self._status = replace(
            self._status,
            connection_state=RfSwitchConnectionState.CONNECTING if initial else RfSwitchConnectionState.RECONNECTING,
            available=False,
            connected=False,
            reconnect_attempts=attempts,
            updated_at_monotonic=time.monotonic(),
        )
        switch: RfSwitch | None = None
        try:
            switch = self._create_switch()
            self._switch = switch
            switch.open()
            # Reconnection always initializes RF8. No previous manual request
            # survives a disconnect.
            status = self._verify_path_locked(RfPath.RF8_WIDEBAND_ANTENNA)
            if not initial:
                logger.info("FT232H RF switch reconnected attempts=%d", attempts)
            return status
        except Exception as error:
            logger.warning("FT232H connection attempt failed backend=%s error=%s", self.backend, error)
            self._mark_failure_locked(error, switch, was_connected=False)
            return self._status

    def _poll_connected_locked(self) -> None:
        switch = self._switch
        if switch is None:
            self._mark_failure_locked(RfSwitchUnavailable("The FT232H RF switch is not connected."), None, was_connected=True)
            return
        requested = self._status.requested_path
        try:
            reported = switch.get_path()
            raw = switch.raw_gpio_value
            address = None if raw is None else gpio_value_to_address(raw)
            if requested is None or reported is not requested or address != PATH_TO_ADDRESS[requested]:
                raise RfSwitchReadbackMismatch(
                    f"requested {None if requested is None else requested.value}, reported {reported.value}, raw={raw!r}"
                )
            self._status = replace(
                self._status,
                hardware_present=True,
                raw_address=address,
                raw_gpio_value=raw,
                updated_at_monotonic=time.monotonic(),
            )
        except Exception as error:
            self._mark_failure_locked(error, switch, was_connected=True)

    def _worker_main(self) -> None:
        while not self._stop_event.wait(self.reconnect_interval_s):
            with self._lock:
                if self._stop_event.is_set():
                    return
                if self._status.connection_state is RfSwitchConnectionState.AVAILABLE:
                    self._poll_connected_locked()
                else:
                    self._connect_locked(initial=False)

    def start(self) -> RfSwitchStatus:
        with self._lock:
            if not self.enabled:
                return self._status
            if self._worker is not None and self._worker.is_alive():
                return self._status
            logger.info("RF switch backend selected backend=%s reconnect_interval_s=%.3f", self.backend, self.reconnect_interval_s)
            self._stop_event.clear()
            status = self._connect_locked(initial=True)
            self._worker = threading.Thread(target=self._worker_main, name="rf-switch-reconnect", daemon=True)
            self._worker.start()
            return status

    def set_path(self, value: str | RfPath) -> RfSwitchStatus:
        path = parse_rf_path(value)
        if not self._lock.acquire(blocking=False):
            raise RfSwitchUnavailable("The FT232H RF switch is not connected.")
        try:
            if not self.enabled or self._status.connection_state is not RfSwitchConnectionState.AVAILABLE:
                raise RfSwitchUnavailable("The FT232H RF switch is not connected.")
            try:
                return self._verify_path_locked(path)
            except Exception as error:
                self._mark_failure_locked(error, self._switch, was_connected=True)
                raise
        finally:
            self._lock.release()

    def stop(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(1.0, min(5.0, self.reconnect_interval_s + 1.0)))
            if worker.is_alive():
                logger.warning("RF-switch reconnect worker did not stop before timeout")
        with self._lock:
            self._worker = None
            switch = self._switch
            present = self._presence(switch)
            if switch is not None:
                if self._status.connection_state is RfSwitchConnectionState.AVAILABLE:
                    try:
                        self._verify_path_locked(RfPath.RF8_WIDEBAND_ANTENNA)
                    except Exception:
                        logger.exception("Shutdown-only RF8 verification failed")
                self._release_switch_locked(switch)
            self._status = replace(
                self._status,
                connection_state=RfSwitchConnectionState.DISABLED if not self.enabled else RfSwitchConnectionState.DISCONNECTED,
                hardware_present=present,
                available=False,
                connected=False,
                requested_path=None,
                reported_path=None,
                expected_fail_safe_path=RfPath.RF8_WIDEBAND_ANTENNA if present else None,
                raw_address=None,
                raw_gpio_value=None,
                readback_matches_request=False,
                verification=RfSwitchVerification.UNVERIFIED if present else RfSwitchVerification.UNAVAILABLE,
                updated_at_monotonic=time.monotonic(),
            )
