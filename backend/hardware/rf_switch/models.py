"""Semantic RF-path models independent of the FT232H transport."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RfPath(str, Enum):
    RF1_DUAL_BAND_LNA = "rf1"
    RF2_AUXILIARY = "rf2"
    RF3_AUXILIARY = "rf3"
    RF4_AUXILIARY = "rf4"
    RF5_AUXILIARY = "rf5"
    RF6_AUXILIARY = "rf6"
    RF7_AUXILIARY = "rf7"
    RF8_WIDEBAND_ANTENNA = "rf8"


class RfSwitchConnectionState(str, Enum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    AVAILABLE = "available"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class RfSwitchVerification(str, Enum):
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    MISMATCH = "mismatch"


PATH_TO_ADDRESS: dict[RfPath, int] = {
    path: index for index, path in enumerate(RfPath)
}
ADDRESS_TO_PATH = {address: path for path, address in PATH_TO_ADDRESS.items()}

PATH_LABELS: dict[RfPath, str] = {
    RfPath.RF1_DUAL_BAND_LNA: "RF1 — 2.4/5.8 GHz LNA",
    RfPath.RF2_AUXILIARY: "RF2 — Auxiliary",
    RfPath.RF3_AUXILIARY: "RF3 — Auxiliary",
    RfPath.RF4_AUXILIARY: "RF4 — Auxiliary",
    RfPath.RF5_AUXILIARY: "RF5 — Auxiliary",
    RfPath.RF6_AUXILIARY: "RF6 — Auxiliary",
    RfPath.RF7_AUXILIARY: "RF7 — Auxiliary",
    RfPath.RF8_WIDEBAND_ANTENNA: "RF8 — Wideband antenna",
}


def parse_rf_path(value: str | RfPath) -> RfPath:
    if isinstance(value, RfPath):
        return value
    try:
        return RfPath(value.strip().lower())
    except (AttributeError, ValueError) as error:
        raise ValueError(f"Unknown RF path {value!r}; expected rf1 through rf8") from error


@dataclass(frozen=True, slots=True)
class RfSwitchStatus:
    connection_state: RfSwitchConnectionState = RfSwitchConnectionState.DISABLED
    hardware_present: bool = False
    available: bool = False
    connected: bool = False
    backend: str = "disabled"
    simulated: bool = False
    requested_path: RfPath | None = None
    reported_path: RfPath | None = None
    expected_fail_safe_path: RfPath | None = None
    raw_address: int | None = None
    raw_gpio_value: int | None = None
    readback_matches_request: bool = False
    verification: RfSwitchVerification = RfSwitchVerification.UNAVAILABLE
    last_error: str | None = None
    reconnect_attempts: int = 0
    last_connected_at: float | None = None
    last_disconnected_at: float | None = None
    updated_at_monotonic: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_state": self.connection_state.value,
            "hardware_present": self.hardware_present,
            "available": self.available,
            "connected": self.connected,
            "backend": self.backend,
            "simulated": self.simulated,
            "requested_path": None if self.requested_path is None else self.requested_path.value,
            "requested_port": None if self.requested_path is None else self.requested_path.value,
            "reported_path": None if self.reported_path is None else self.reported_path.value,
            "reported_port": None if self.reported_path is None else self.reported_path.value,
            "expected_fail_safe_path": None if self.expected_fail_safe_path is None else self.expected_fail_safe_path.value,
            "raw_address": self.raw_address,
            "raw_gpio_value": self.raw_gpio_value,
            "gpio_value": self.raw_gpio_value,
            "readback_matches_request": self.readback_matches_request,
            "verification": self.verification.value,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "last_connected_at": self.last_connected_at,
            "last_disconnected_at": self.last_disconnected_at,
            "updated_at_monotonic": self.updated_at_monotonic,
        }


def capabilities_payload(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "default_path": RfPath.RF8_WIDEBAND_ANTENNA.value,
        "selection_policy": "session-only-manual",
        "paths": [
            {
                "id": path.value,
                "rf_channel": f"RF{PATH_TO_ADDRESS[path] + 1}",
                "address": PATH_TO_ADDRESS[path],
                "label": PATH_LABELS[path],
                "external_lna": path is RfPath.RF1_DUAL_BAND_LNA,
            }
            for path in RfPath
        ],
    }
