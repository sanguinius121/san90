"""Backend-owned sequential center-frequency scan controller."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from backend.analyzer.errors import ControlError, ControlErrorCode

DEFAULT_SCAN_DWELL_SECONDS = 5.0
MIN_SCAN_DWELL_SECONDS = 0.5
SCAN_DWELL_STEP_SECONDS = 0.5
MAX_SCAN_ENTRIES = 128

FrequencyScanState = Literal["idle", "tuning", "dwelling", "stopping", "error"]
TuneCallback = Callable[[float], Awaitable[float]]
AvailabilityCallback = Callable[[], bool]
StatusCallback = Callable[[], None]
SleepCallback = Callable[[float], Awaitable[None]]
ClockCallback = Callable[[], float]


@dataclass(frozen=True, slots=True)
class FrequencyScanEntry:
    id: str
    enabled: bool
    center_frequency_hz: float
    duration_seconds: float


def validate_frequency_scan_entries(
    entries: Sequence[FrequencyScanEntry],
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> tuple[FrequencyScanEntry, ...]:
    if len(entries) > MAX_SCAN_ENTRIES:
        raise ControlError(
            ControlErrorCode.VALUE_OUT_OF_RANGE,
            f"Frequency scan supports at most {MAX_SCAN_ENTRIES} entries",
            recoverable=True,
        )
    seen_ids: set[str] = set()
    validated: list[FrequencyScanEntry] = []
    for entry in entries:
        if not entry.id or len(entry.id) > 64 or entry.id in seen_ids:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                "Frequency scan entry IDs must be non-empty, unique, and at most 64 characters",
                requested_value=entry.id,
                recoverable=True,
            )
        seen_ids.add(entry.id)
        if (
            not math.isfinite(entry.center_frequency_hz)
            or entry.center_frequency_hz <= 0
            or entry.center_frequency_hz < minimum_frequency_hz
            or entry.center_frequency_hz > maximum_frequency_hz
        ):
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                f"Frequency scan center must be between {minimum_frequency_hz} Hz and {maximum_frequency_hz} Hz",
                requested_value=entry.center_frequency_hz,
                recoverable=True,
            )
        if not math.isfinite(entry.duration_seconds) or entry.duration_seconds < MIN_SCAN_DWELL_SECONDS:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                f"Frequency scan duration must be at least {MIN_SCAN_DWELL_SECONDS} seconds",
                requested_value=entry.duration_seconds,
                recoverable=True,
            )
        validated.append(entry)
    return tuple(validated)


class FrequencyScanController:
    """Runs one bounded, cancellation-safe sequential scan loop."""

    def __init__(
        self,
        tune: TuneCallback,
        available: AvailabilityCallback,
        status_changed: StatusCallback,
        *,
        sleep: SleepCallback = asyncio.sleep,
        clock: ClockCallback = time.monotonic,
    ) -> None:
        self._tune = tune
        self._available = available
        self._status_changed = status_changed
        self._sleep = sleep
        self._clock = clock
        self._entries: tuple[FrequencyScanEntry, ...] = ()
        self._task: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._state: FrequencyScanState = "idle"
        self._active_entry_id: str | None = None
        self._active_index: int | None = None
        self._active_count = 0
        self._verified_center_frequency_hz: float | None = None
        self._dwell_duration_seconds: float | None = None
        self._dwell_deadline: float | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def entries(self) -> tuple[FrequencyScanEntry, ...]:
        return self._entries

    def configure(
        self,
        entries: Sequence[FrequencyScanEntry],
        *,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> None:
        if self.running:
            raise ControlError(
                ControlErrorCode.DEVICE_BUSY,
                "Frequency scan configuration cannot change while scanning",
                recoverable=True,
            )
        self._entries = validate_frequency_scan_entries(
            entries,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
        )
        self._active_count = sum(entry.enabled for entry in self._entries)
        self._last_error = None
        if self._state == "error":
            self._state = "idle"
        self._notify()

    async def start(
        self,
        *,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> None:
        if self.running:
            raise ControlError(
                ControlErrorCode.DEVICE_BUSY,
                "Frequency scan is already running",
                recoverable=True,
            )
        entries = validate_frequency_scan_entries(
            self._entries,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
        )
        enabled = tuple(entry for entry in entries if entry.enabled)
        if not entries:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                "Frequency scan has no entries",
                recoverable=True,
            )
        if not enabled:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                "Frequency scan requires at least one enabled entry",
                recoverable=True,
            )
        if not self._available():
            raise ControlError(
                ControlErrorCode.DEVICE_NOT_CONNECTED,
                "Analyzer is unavailable for frequency scan",
                recoverable=True,
            )
        self._last_error = None
        self._active_count = len(enabled)
        self._stop_requested = False
        self._state = "tuning"
        self._task = asyncio.create_task(self._run(enabled), name="frequency-scan")
        self._notify()

    async def stop(self, *, reason: str | None = None) -> None:
        task = self._task
        if task is not None and not task.done():
            was_tuning = self._state == "tuning"
            self._stop_requested = True
            self._state = "stopping"
            self._notify()
            if not was_tuning:
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._clear_active()
        if reason:
            self._state = "error"
            self._last_error = reason
        else:
            self._state = "idle"
            self._last_error = None
        self._notify()

    def status_payload(self) -> dict[str, object]:
        remaining = None
        if self._state == "dwelling" and self._dwell_deadline is not None:
            remaining = max(0.0, self._dwell_deadline - self._clock())
        return {
            "running": self.running,
            "state": self._state,
            "active_entry_id": self._active_entry_id,
            "active_index": self._active_index,
            "active_count": self._active_count,
            "verified_center_frequency_hz": self._verified_center_frequency_hz,
            "dwell_duration_seconds": self._dwell_duration_seconds,
            "remaining_dwell_seconds": remaining,
            "last_error": self._last_error,
        }

    def payload(self) -> dict[str, object]:
        return {
            "entries": [asdict(entry) for entry in self._entries],
            **self.status_payload(),
        }

    async def _run(self, enabled: tuple[FrequencyScanEntry, ...]) -> None:
        try:
            while True:
                for index, entry in enumerate(enabled, start=1):
                    if self._stop_requested:
                        return
                    self._ensure_available()
                    self._state = "tuning"
                    self._active_entry_id = entry.id
                    self._active_index = index
                    self._dwell_duration_seconds = entry.duration_seconds
                    self._dwell_deadline = None
                    self._notify()
                    actual_hz = await self._tune(entry.center_frequency_hz)
                    if self._stop_requested:
                        return
                    if not math.isfinite(actual_hz) or actual_hz <= 0:
                        raise RuntimeError("Frequency scan tune returned an invalid hardware readback")
                    tolerance_hz = max(1.0, abs(entry.center_frequency_hz) * 1e-12)
                    if abs(actual_hz - entry.center_frequency_hz) > tolerance_hz:
                        raise RuntimeError(
                            f"Frequency scan tune readback {actual_hz} Hz did not match request "
                            f"{entry.center_frequency_hz} Hz"
                        )
                    self._ensure_available()
                    self._verified_center_frequency_hz = actual_hz
                    self._state = "dwelling"
                    self._dwell_deadline = self._clock() + entry.duration_seconds
                    self._notify()
                    await self._wait_for_dwell()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._last_error = str(error)
            self._state = "error"
            self._clear_active()
            self._notify()
        finally:
            self._task = None
            if self._state not in {"error", "stopping"}:
                self._state = "idle"
                self._clear_active()
                self._notify()

    async def _wait_for_dwell(self) -> None:
        while self._dwell_deadline is not None:
            self._ensure_available()
            remaining = self._dwell_deadline - self._clock()
            if remaining <= 0:
                return
            await self._sleep(min(0.1, remaining))

    def _ensure_available(self) -> None:
        if not self._available():
            raise RuntimeError("Analyzer became unavailable during frequency scan")

    def _clear_active(self) -> None:
        self._active_entry_id = None
        self._active_index = None
        self._dwell_duration_seconds = None
        self._dwell_deadline = None

    def _notify(self) -> None:
        self._status_changed()
