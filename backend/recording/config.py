"""Durable, backend-owned recording preferences and safe output resolution."""

from __future__ import annotations

import errno
import json
import logging
import math
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import RecordingConfig, RecordingMode
from .storage import (
    DEFAULT_FREE_DISK_RESERVE_BYTES,
    RecordingStorage,
    validate_file_prefix,
    validate_recording_config_limits,
)

logger = logging.getLogger("san90.recording.config")

RECORDING_CONFIG_SCHEMA_VERSION = 1
DEFAULT_RECORDING_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "recording.json"
RECORDING_ROOT_ENV = "SAN90_RECORDING_ROOT"
DEFAULT_RECORDING_ROOT = Path.home() / "SAN90_Recordings"


def configured_recording_root() -> Path:
    """Return the backend-owned root, outside the repository by default."""
    configured = os.getenv(RECORDING_ROOT_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_RECORDING_ROOT


@dataclass(frozen=True, slots=True)
class RecordingPreferences:
    mode: RecordingMode = RecordingMode.FIXED
    duration_s: float | None = 5.0
    file_size_limit_bytes: int = 4 * 1024**3
    free_disk_reserve_bytes: int = DEFAULT_FREE_DISK_RESERVE_BYTES
    output_directory: str = "."
    file_prefix: str = "SAN90_RTA"

    def as_json(self) -> dict[str, Any]:
        return {
            "version": RECORDING_CONFIG_SCHEMA_VERSION,
            "mode": self.mode.value,
            "duration_s": self.duration_s,
            "file_size_limit_bytes": self.file_size_limit_bytes,
            "free_disk_reserve_bytes": self.free_disk_reserve_bytes,
            "output_directory": self.output_directory,
            "file_prefix": self.file_prefix,
        }


class RecordingConfigStore:
    """Persists preferences; runtime state is deliberately not represented."""

    def __init__(
        self,
        *,
        path: str | Path | None = DEFAULT_RECORDING_CONFIG_PATH,
        recording_root: str | Path | None = None,
    ) -> None:
        self.path = None if path is None else Path(path)
        self.recording_root = (
            configured_recording_root()
            if recording_root is None
            else Path(recording_root).expanduser()
        )
        self.preferences = RecordingPreferences()
        self.load_warning: str | None = None
        self.save_error: str | None = None

    def load(self) -> RecordingPreferences:
        self.load_warning = None
        path = self.path
        if path is None:
            self.preferences = self.validate(self.preferences)
            return self.preferences
        if not path.exists():
            self.preferences = self.validate(self.preferences)
            return self.preferences
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != RECORDING_CONFIG_SCHEMA_VERSION:
                raise ValueError("unsupported recording configuration schema")
            self.preferences = self.validate(self._from_document(document))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            self.load_warning = f"Unable to load recording configuration: {error}; using defaults"
            logger.warning(self.load_warning)
            self.preferences = self.validate(RecordingPreferences())
        return self.preferences

    def save(self, preferences: RecordingPreferences) -> RecordingPreferences:
        validated = self.validate(preferences)
        self.resolve_output_directory(validated.output_directory, create=True)
        path = self.path
        if path is None:
            self.preferences = validated
            return validated
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(validated.as_json(), sort_keys=True, separators=(",", ":")) + "\n"
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.save_error = None
        except OSError as error:
            self.save_error = f"Unable to save recording configuration: {error}"
            logger.error(self.save_error)
            raise
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        self.preferences = validated
        return validated

    def validate(self, value: RecordingPreferences) -> RecordingPreferences:
        mode = RecordingMode(value.mode)
        duration = value.duration_s
        if mode == RecordingMode.FIXED:
            if (
                duration is None
                or isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration <= 0
            ):
                raise ValueError("fixed recording requires a finite positive duration_s")
        elif duration is not None and (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise ValueError("duration_s must be null or finite and positive")
        if isinstance(value.file_size_limit_bytes, bool) or not isinstance(
            value.file_size_limit_bytes, int
        ):
            raise ValueError("file_size_limit_bytes must be an integer")
        if isinstance(value.free_disk_reserve_bytes, bool) or not isinstance(
            value.free_disk_reserve_bytes, int
        ):
            raise ValueError("free_disk_reserve_bytes must be an integer")
        if not isinstance(value.output_directory, str):
            raise ValueError("output_directory must be a string")
        if not isinstance(value.file_prefix, str):
            raise ValueError("file_prefix must be a string")
        validate_recording_config_limits(
            value.file_size_limit_bytes, value.free_disk_reserve_bytes
        )
        validate_file_prefix(value.file_prefix)
        relative = Path(value.output_directory)
        if relative.is_absolute() or any(part in {"", ".."} for part in relative.parts):
            raise ValueError("output_directory must be a safe relative directory under the recording root")
        if any(ord(character) < 32 or ord(character) == 127 for character in value.output_directory):
            raise ValueError("output_directory must not contain control characters")
        return RecordingPreferences(
            mode,
            float(duration) if mode == RecordingMode.FIXED else None,
            int(value.file_size_limit_bytes),
            int(value.free_disk_reserve_bytes),
            value.output_directory,
            value.file_prefix,
        )

    def runtime_config(self) -> RecordingConfig:
        value = self.preferences
        return RecordingConfig(
            value.mode,
            self.resolve_output_directory(value.output_directory, create=True),
            value.file_prefix,
            value.duration_s,
            value.file_size_limit_bytes,
            value.free_disk_reserve_bytes,
        )

    def resolve_output_directory(self, relative_text: str, *, create: bool) -> Path:
        if create:
            self.recording_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        elif not self.recording_root.exists():
            raise FileNotFoundError(self.recording_root)
        root = self.recording_root.resolve(strict=True)
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("output directory escapes the backend recording root")
        candidate = root.joinpath(relative)
        if create:
            try:
                self._create_relative_directory(root, relative)
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError(
                        "output directory contains a symlink or non-directory component"
                    ) from error
                raise
        resolved = candidate.resolve(strict=True)
        if resolved != root and root not in resolved.parents:
            raise ValueError("output directory symlink escapes the backend recording root")
        RecordingStorage(resolved, create=False)
        return resolved

    def list_output_directories(self) -> list[str]:
        """List safe relative directories without following symlinks."""
        root = self.resolve_output_directory(".", create=True)
        directories = ["."]
        pending = [root]
        while pending:
            parent = pending.pop()
            try:
                entries = sorted(os.scandir(parent), key=lambda entry: entry.name.casefold())
            except OSError as error:
                raise OSError(f"Unable to list recording directory {parent.name}: {error}") from error
            for entry in entries:
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                except OSError:
                    continue
                if not stat.S_ISDIR(mode):
                    continue
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                directories.append(relative)
                pending.append(path)
                if len(directories) >= 1_000:
                    return directories
        return directories

    @staticmethod
    def _create_relative_directory(root: Path, relative: Path) -> None:
        """Create components with dir-fd/O_NOFOLLOW so symlinks cannot escape."""
        components = relative.parts
        if not components:
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(root, flags)
        try:
            for component in components:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        finally:
            os.close(descriptor)

    @staticmethod
    def _from_document(document: Mapping[str, Any]) -> RecordingPreferences:
        return RecordingPreferences(
            mode=RecordingMode(document["mode"]),
            duration_s=document.get("duration_s"),
            file_size_limit_bytes=document["file_size_limit_bytes"],
            free_disk_reserve_bytes=document["free_disk_reserve_bytes"],
            output_directory=document.get("output_directory", "."),
            file_prefix=document["file_prefix"],
        )
