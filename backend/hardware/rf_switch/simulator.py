"""Deterministic RF-switch simulator used by development and tests."""

from __future__ import annotations

import threading

from .base import RfSwitch
from .errors import RfSwitchReadbackMismatch, RfSwitchUnavailable
from .ft232h_switch import address_to_gpio_value
from .models import ADDRESS_TO_PATH, PATH_TO_ADDRESS, RfPath


class SimulatorRfSwitch(RfSwitch):
    def __init__(self) -> None:
        self._connected = False
        self._path = RfPath.RF8_WIDEBAND_ANTENNA
        self._raw = address_to_gpio_value(7)
        self.connection_error: str | None = None
        self.read_error: str | None = None
        self.readback_override_address: int | None = None
        self.present = True
        self._lock = threading.RLock()

    @property
    def raw_gpio_value(self) -> int | None:
        return self._raw if self._connected else None

    def open(self) -> None:
        with self._lock:
            if not self.present:
                raise RfSwitchUnavailable("FT232H is not connected")
            if self.connection_error:
                raise RfSwitchUnavailable(self.connection_error)
            self._connected = True
            self._path = RfPath.RF8_WIDEBAND_ANTENNA
            self._raw = address_to_gpio_value(7)

    def close(self) -> None:
        with self._lock:
            self._path = RfPath.RF8_WIDEBAND_ANTENNA
            self._raw = address_to_gpio_value(7)
            self._connected = False

    def _require_connected(self) -> None:
        if not self.present or not self._connected:
            raise RfSwitchUnavailable("Simulated RF switch is not open")

    def is_hardware_present(self) -> bool:
        return self.present

    def set_path(self, path: RfPath) -> None:
        if not isinstance(path, RfPath):
            raise ValueError("path must be an RfPath")
        with self._lock:
            self._require_connected()
            requested = PATH_TO_ADDRESS[path]
            reported = self.readback_override_address
            if reported is None:
                reported = requested
            if not 0 <= reported <= 7:
                raise ValueError("readback_override_address must be between 0 and 7")
            self._raw = address_to_gpio_value(reported)
            self._path = ADDRESS_TO_PATH[reported]
            if reported != requested:
                raise RfSwitchReadbackMismatch(
                    f"requested {requested:03b}, simulated readback {reported:03b}"
                )

    def get_path(self) -> RfPath:
        with self._lock:
            self._require_connected()
            if self.read_error:
                raise RfSwitchUnavailable(self.read_error)
            return self._path
