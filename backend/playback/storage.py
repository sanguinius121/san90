"""Secure catalog and opaque recording-ID resolution."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.recording.format import RecordingFormatError

from .index import build_playback_index
from .models import RecordingSummary


class RecordingCatalog:
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)

    @staticmethod
    def _id(relative_path: str) -> str:
        return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:32]

    def _safe_files(self):
        for path in self.root.rglob("*.san90rta"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                if self.root not in resolved.parents:
                    continue
                relative = resolved.relative_to(self.root).as_posix()
                yield relative, resolved
            except (OSError, ValueError):
                continue

    def resolve(self, recording_id: str) -> Path:
        if not recording_id or len(recording_id) != 32 or any(c not in "0123456789abcdef" for c in recording_id):
            raise FileNotFoundError("unknown recording")
        for relative, path in self._safe_files():
            if self._id(relative) == recording_id:
                return path
        raise FileNotFoundError("unknown recording")

    def list(self) -> list[RecordingSummary]:
        return [self._summary(relative, path) for relative, path in self._safe_files()]

    def get(self, recording_id: str) -> RecordingSummary:
        path = self.resolve(recording_id)
        relative = path.relative_to(self.root).as_posix()
        return self._summary(relative, path)

    def _summary(self, relative: str, path: Path) -> RecordingSummary:
        stat = path.stat()
        try:
            index = build_playback_index(path)
            end = index.end
            reason = getattr(end.stop_reason, "name", None)
            created = datetime.fromtimestamp(
                index.creation_unix_ns / 1e9, tz=timezone.utc
            ).astimezone().isoformat()
            return RecordingSummary(
                self._id(relative), relative, stat.st_size, created, index.duration_s,
                end.trace_count, len(index.batches), len(index.configurations),
                end.gap_count, end.lost_trace_count,
                reason.lower() if reason else str(end.stop_reason), True, True, True,
            )
        except (OSError, RecordingFormatError, ValueError) as error:
            created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone().isoformat()
            return RecordingSummary(
                self._id(relative), relative, stat.st_size, created, 0.0, 0, 0, 0, 0, 0,
                None, False, False, False, str(error),
            )
