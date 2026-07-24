"""Structured errors for RF-switch API responses."""

from __future__ import annotations


class RfSwitchError(RuntimeError):
    code = "rf_switch_error"
    http_status = 502


class RfSwitchUnavailable(RfSwitchError):
    code = "rf_switch_unavailable"
    http_status = 503


class RfSwitchBusy(RfSwitchError):
    code = "rf_switch_busy"
    http_status = 409


class RfSwitchPermissionDenied(RfSwitchError):
    code = "rf_switch_permission_denied"
    http_status = 403


class RfSwitchReadbackMismatch(RfSwitchError):
    code = "rf_switch_readback_mismatch"
    http_status = 502
