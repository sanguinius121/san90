"""Validated, durable GRAY8 power-range configuration."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .power_profiles import DEFAULT_POWER_PROFILE, POWER_PROFILES, PowerProfile


POWER_MIN_DBM = -140.0
POWER_MAX_DBM = 10.0
MIN_POWER_RANGE_DB = 10.0
POWER_RANGE_SCHEMA_VERSION = 1
DEFAULT_POWER_RANGE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ai-power-range.json"


def _matching_preset(low: float, high: float) -> str | None:
    for name, profile in POWER_PROFILES.items():
        if low == profile.min_dbm and high == profile.max_dbm:
            return name
    return None


@dataclass(frozen=True, slots=True)
class AiPowerRangeConfig:
    power_min_dbm: float
    power_max_dbm: float
    generation: int = 0

    @property
    def preset(self) -> str | None:
        return _matching_preset(self.power_min_dbm, self.power_max_dbm)

    @property
    def mode(self) -> str:
        return "preset" if self.preset is not None else "custom"

    @property
    def range_db(self) -> float:
        return self.power_max_dbm - self.power_min_dbm

    @property
    def db_per_gray_level(self) -> float:
        return self.range_db / 255.0

    def as_profile(self) -> PowerProfile:
        return PowerProfile(
            self.preset or "custom",
            self.power_min_dbm,
            self.power_max_dbm,
            self.generation,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "preset": self.preset,
            "power_min_dbm": self.power_min_dbm,
            "power_max_dbm": self.power_max_dbm,
            "range_db": self.range_db,
            "db_per_gray_level": self.db_per_gray_level,
            "generation": self.generation,
            "supported_min_dbm": POWER_MIN_DBM,
            "supported_max_dbm": POWER_MAX_DBM,
            "minimum_range_db": MIN_POWER_RANGE_DB,
        }


def validate_power_range(low: float, high: float, *, generation: int = 0) -> AiPowerRangeConfig:
    if isinstance(low, bool) or isinstance(high, bool):
        raise ValueError("AI power range values must be finite numbers")
    low_value, high_value = float(low), float(high)
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        raise ValueError("AI power range values must be finite")
    if low_value < POWER_MIN_DBM or high_value > POWER_MAX_DBM:
        raise ValueError(f"AI power range must stay within {POWER_MIN_DBM:g} to {POWER_MAX_DBM:g} dBm")
    if high_value <= low_value:
        raise ValueError("power_max_dbm must be greater than power_min_dbm")
    if high_value - low_value < MIN_POWER_RANGE_DB:
        raise ValueError(f"AI power range must span at least {MIN_POWER_RANGE_DB:g} dB")
    if generation < 0:
        raise ValueError("AI power range generation must be non-negative")
    return AiPowerRangeConfig(low_value, high_value, generation)


class AiPowerRangeStore:
    """Atomic immutable runtime snapshot plus atomically persisted preferences."""

    def __init__(self, path: str | Path | None = DEFAULT_POWER_RANGE_CONFIG_PATH) -> None:
        self.path = None if path is None else Path(path)
        default = POWER_PROFILES[DEFAULT_POWER_PROFILE]
        self._current = validate_power_range(default.min_dbm, default.max_dbm)
        self._lock = threading.Lock()
        self.load_warning: str | None = None

    def current(self) -> AiPowerRangeConfig:
        return self._current

    def load(self) -> AiPowerRangeConfig:
        path = self.path
        if path is None or not path.exists():
            return self._current
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, Mapping) or document.get("version") != POWER_RANGE_SCHEMA_VERSION:
                raise ValueError("unsupported AI power-range configuration schema")
            loaded = validate_power_range(document["power_min_dbm"], document["power_max_dbm"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            self.load_warning = f"Unable to load AI power range: {error}; using External LNA defaults"
            return self._current
        self._current = loaded
        self.load_warning = None
        return loaded

    def update(self, low: float, high: float) -> AiPowerRangeConfig:
        validated = validate_power_range(low, high)
        with self._lock:
            current = self._current
            if (validated.power_min_dbm, validated.power_max_dbm) == (
                current.power_min_dbm,
                current.power_max_dbm,
            ):
                return current
            updated = validate_power_range(low, high, generation=current.generation + 1)
            self._persist(updated)
            self._current = updated
            return updated

    def update_preset(self, name: str) -> AiPowerRangeConfig:
        try:
            profile = POWER_PROFILES[name]
        except KeyError as error:
            raise ValueError(f"unknown AI power profile {name!r}; expected one of {tuple(POWER_PROFILES)}") from error
        return self.update(profile.min_dbm, profile.max_dbm)

    def _persist(self, value: AiPowerRangeConfig) -> None:
        path = self.path
        if path is None:
            return
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "version": POWER_RANGE_SCHEMA_VERSION,
                "power_min_dbm": value.power_min_dbm,
                "power_max_dbm": value.power_max_dbm,
            },
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
