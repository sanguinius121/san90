"""Backend-owned sequential center-frequency scan controller and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from backend.analyzer.errors import ControlError, ControlErrorCode

logger = logging.getLogger("san90.frequency_scan")

DEFAULT_SCAN_DURATION_MS = 5_000
MIN_SCAN_DURATION_MS = 500
SCAN_DURATION_STEP_MS = 500
DEFAULT_SCAN_STEP_HZ = 10_000_000
MAX_SCAN_ENTRIES = 128
FREQUENCY_SCAN_SCHEMA_VERSION = 1
FREQUENCY_SCAN_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "frequency-scan.json"

FrequencyUnit = Literal["MHz", "GHz"]
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
    duration_ms: int
    step_hz: float = DEFAULT_SCAN_STEP_HZ
    display_unit: FrequencyUnit = "GHz"
    step_unit: FrequencyUnit = "MHz"


DEFAULT_FREQUENCY_SCAN_ENTRIES = (
    FrequencyScanEntry("scan-entry-1", True, 400_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="MHz"),
    FrequencyScanEntry("scan-entry-2", True, 900_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="MHz"),
    FrequencyScanEntry("scan-entry-3", True, 2_440_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="GHz"),
    FrequencyScanEntry("scan-entry-4", True, 3_300_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="GHz"),
    FrequencyScanEntry("scan-entry-5", True, 5_000_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="GHz"),
    FrequencyScanEntry("scan-entry-6", True, 5_775_000_000, DEFAULT_SCAN_DURATION_MS, display_unit="MHz"),
)


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
    maximum_step_hz = maximum_frequency_hz - minimum_frequency_hz
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
        if (
            isinstance(entry.duration_ms, bool)
            or not isinstance(entry.duration_ms, int)
            or entry.duration_ms < MIN_SCAN_DURATION_MS
        ):
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                f"Frequency scan duration must be at least {MIN_SCAN_DURATION_MS} milliseconds",
                requested_value=entry.duration_ms,
                recoverable=True,
            )
        if (
            not math.isfinite(entry.step_hz)
            or entry.step_hz <= 0
            or entry.step_hz > maximum_step_hz
        ):
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                f"Frequency scan step must be greater than zero and no more than {maximum_step_hz} Hz",
                requested_value=entry.step_hz,
                recoverable=True,
            )
        if entry.display_unit not in {"MHz", "GHz"} or entry.step_unit not in {"MHz", "GHz"}:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                "Frequency scan display units must be MHz or GHz",
                requested_value={"display_unit": entry.display_unit, "step_unit": entry.step_unit},
                recoverable=True,
            )
        validated.append(entry)
    return tuple(validated)


class FrequencyScanController:
    """Runs one bounded sequential scan loop with durable configuration."""

    def __init__(
        self,
        tune: TuneCallback,
        available: AvailabilityCallback,
        status_changed: StatusCallback,
        *,
        sleep: SleepCallback = asyncio.sleep,
        clock: ClockCallback = time.monotonic,
        config_path: str | Path | None = None,
    ) -> None:
        self._tune = tune
        self._available = available
        self._status_changed = status_changed
        self._sleep = sleep
        self._clock = clock
        self._config_path = None if config_path is None else Path(config_path)
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
        self._configuration_save_error: str | None = None
        self._configuration_load_warning: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def entries(self) -> tuple[FrequencyScanEntry, ...]:
        return self._entries

    def load_configuration(
        self,
        *,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> None:
        """Load durable entries, always resetting transient controller state."""
        self._reset_transient_state()
        self._configuration_load_warning = None
        path = self._config_path
        if path is None:
            self._set_entries(
                validate_frequency_scan_entries(
                    DEFAULT_FREQUENCY_SCAN_ENTRIES,
                    minimum_frequency_hz=minimum_frequency_hz,
                    maximum_frequency_hz=maximum_frequency_hz,
                )
            )
            self._notify()
            return
        if not path.exists():
            self._set_entries(
                validate_frequency_scan_entries(
                    DEFAULT_FREQUENCY_SCAN_ENTRIES,
                    minimum_frequency_hz=minimum_frequency_hz,
                    maximum_frequency_hz=maximum_frequency_hz,
                )
            )
            self._save_configuration()
            self._notify()
            return
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != FREQUENCY_SCAN_SCHEMA_VERSION:
                raise ValueError(f"unsupported schema version {document.get('version') if isinstance(document, dict) else None}")
            raw_entries = document.get("entries")
            if not isinstance(raw_entries, list):
                raise ValueError("entries must be an array")
            loaded = tuple(self._entry_from_json(value) for value in raw_entries)
            self._set_entries(
                validate_frequency_scan_entries(
                    loaded,
                    minimum_frequency_hz=minimum_frequency_hz,
                    maximum_frequency_hz=maximum_frequency_hz,
                )
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, ControlError) as error:
            warning = f"Unable to load frequency scan configuration from {path}: {error}; using defaults"
            logger.warning(warning)
            self._configuration_load_warning = warning
            self._set_entries(
                validate_frequency_scan_entries(
                    DEFAULT_FREQUENCY_SCAN_ENTRIES,
                    minimum_frequency_hz=minimum_frequency_hz,
                    maximum_frequency_hz=maximum_frequency_hz,
                )
            )
        self._notify()

    def configure(
        self,
        entries: Sequence[FrequencyScanEntry],
        *,
        minimum_frequency_hz: float,
        maximum_frequency_hz: float,
    ) -> None:
        validated = validate_frequency_scan_entries(
            entries,
            minimum_frequency_hz=minimum_frequency_hz,
            maximum_frequency_hz=maximum_frequency_hz,
        )
        self._set_entries(validated)
        self._last_error = None
        if self._state == "error":
            self._state = "idle"
        self._configuration_load_warning = None
        self._save_configuration()
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
            raise ControlError(ControlErrorCode.VALUE_OUT_OF_RANGE, "Frequency scan has no entries", recoverable=True)
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
        self._task = asyncio.create_task(self._run(), name="frequency-scan")
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
            "configuration_save_error": self._configuration_save_error,
            "configuration_load_warning": self._configuration_load_warning,
        }

    def payload(self) -> dict[str, object]:
        return {"entries": [asdict(entry) for entry in self._entries], **self.status_payload()}

    async def _run(self) -> None:
        previous_entry_id: str | None = None
        try:
            while not self._stop_requested:
                enabled = tuple(entry for entry in self._entries if entry.enabled)
                self._active_count = len(enabled)
                if not enabled:
                    return
                entry_index = 0
                if previous_entry_id is not None:
                    previous_index = next(
                        (index for index, entry in enumerate(enabled) if entry.id == previous_entry_id),
                        None,
                    )
                    if previous_index is not None:
                        entry_index = (previous_index + 1) % len(enabled)
                entry = enabled[entry_index]
                self._ensure_available()
                self._state = "tuning"
                self._active_entry_id = entry.id
                self._active_index = entry_index + 1
                self._dwell_duration_seconds = entry.duration_ms / 1000
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
                self._dwell_deadline = self._clock() + entry.duration_ms / 1000
                self._notify()
                await self._wait_for_dwell()
                previous_entry_id = entry.id
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

    def _save_configuration(self) -> None:
        path = self._config_path
        if path is None:
            return
        document = {
            "version": FREQUENCY_SCAN_SCHEMA_VERSION,
            "entries": [asdict(entry) for entry in self._entries],
        }
        temporary_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(document, temporary, indent=2, allow_nan=False)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._configuration_save_error = None
        except (OSError, TypeError, ValueError) as error:
            self._configuration_save_error = f"Unable to save frequency scan configuration to {path}: {error}"
            logger.error(self._configuration_save_error)
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _entry_from_json(value: object) -> FrequencyScanEntry:
        if not isinstance(value, dict):
            raise ValueError("each entry must be an object")
        required = {
            "id",
            "enabled",
            "center_frequency_hz",
            "duration_ms",
            "step_hz",
            "display_unit",
            "step_unit",
        }
        if set(value) != required:
            raise ValueError(f"entry fields must be exactly {sorted(required)}")
        if not isinstance(value["id"], str) or not isinstance(value["enabled"], bool):
            raise ValueError("entry id and enabled values have invalid types")
        if isinstance(value["duration_ms"], bool) or not isinstance(value["duration_ms"], int):
            raise ValueError("duration_ms must be an integer")
        for name in ("center_frequency_hz", "step_hz"):
            if isinstance(value[name], bool) or not isinstance(value[name], (int, float)):
                raise ValueError(f"{name} must be numeric")
        return FrequencyScanEntry(
            id=value["id"],
            enabled=value["enabled"],
            center_frequency_hz=float(value["center_frequency_hz"]),
            duration_ms=value["duration_ms"],
            step_hz=float(value["step_hz"]),
            display_unit=value["display_unit"],
            step_unit=value["step_unit"],
        )

    def _set_entries(self, entries: tuple[FrequencyScanEntry, ...]) -> None:
        self._entries = entries
        self._active_count = sum(entry.enabled for entry in entries)

    def _reset_transient_state(self) -> None:
        self._task = None
        self._stop_requested = False
        self._state = "idle"
        self._last_error = None
        self._verified_center_frequency_hz = None
        self._clear_active()

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
