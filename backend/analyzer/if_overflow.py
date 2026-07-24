"""Classification and short-lived status latch for SAN-90 IF overflow."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .htra import (
    API_LAST_PACKET,
    API_LAST_PACKET_WITH_TRIGGER_MISSED,
    API_NO_ERROR,
    API_TRIGGER_MISSED,
    API_WARNING_BUS_TIMEOUT,
    API_WARNING_DATA_NOT_READY,
    API_WARNING_IF_OVERFLOW,
)


@dataclass(frozen=True, slots=True)
class RtaReadClassification:
    process_trace: bool
    if_overflow: bool = False
    fatal: bool = False


def classify_rta_read_status(status: int) -> RtaReadClassification:
    """Classify an RTA read without treating the SDK overflow warning as fatal."""
    if status == API_NO_ERROR:
        return RtaReadClassification(process_trace=True)
    if status == API_WARNING_IF_OVERFLOW:
        return RtaReadClassification(process_trace=True, if_overflow=True)
    if status in {
        API_WARNING_BUS_TIMEOUT,
        API_WARNING_DATA_NOT_READY,
        API_LAST_PACKET,
        API_TRIGGER_MISSED,
        API_LAST_PACKET_WITH_TRIGGER_MISSED,
    }:
        return RtaReadClassification(process_trace=False)
    return RtaReadClassification(process_trace=False, fatal=True)


class IfOverflowLatch:
    """Keep a momentary overflow warning visible for a monotonic hold period."""

    def __init__(self, hold_seconds: float = 0.9) -> None:
        if hold_seconds <= 0:
            raise ValueError("IF overflow hold period must be positive")
        self.hold_ns = round(hold_seconds * 1e9)
        self._active_until_ns = 0

    def note_overflow(self, now_ns: int | None = None) -> None:
        now = time.monotonic_ns() if now_ns is None else now_ns
        self._active_until_ns = max(self._active_until_ns, now + self.hold_ns)

    def active(self, now_ns: int | None = None) -> bool:
        now = time.monotonic_ns() if now_ns is None else now_ns
        return now < self._active_until_ns

    def clear(self) -> None:
        self._active_until_ns = 0
