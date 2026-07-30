"""Safe filesystem lifecycle helpers for SAN-90 recordings."""

from __future__ import annotations

import ctypes
import errno
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


DEFAULT_FREE_DISK_RESERVE_BYTES = 2 * 1024**3
FINALIZATION_RESERVE_BYTES = 4096
FREE_SPACE_CHECK_INTERVAL_S = 0.250
FREE_SPACE_CHECK_BYTES = 64 * 1024**2
MIN_FILE_SIZE_LIMIT_BYTES = 16 * 1024
_PREFIX_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_RENAME_NOREPLACE = 1


class RecordingStorageError(OSError):
    pass


@dataclass(frozen=True, slots=True)
class StorageSession:
    root: Path
    part_path: Path
    final_path: Path
    fd: int


def validate_file_prefix(prefix: str) -> str:
    if not _PREFIX_RE.fullmatch(prefix) or ".." in prefix:
        raise ValueError(
            "file prefix must match [A-Za-z0-9][A-Za-z0-9._-]{0,63} and must not contain '..'"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in prefix):
        raise ValueError("file prefix must not contain control characters")
    return prefix


def validate_recording_config_limits(file_size_limit_bytes: int, free_disk_reserve_bytes: int) -> None:
    if file_size_limit_bytes < MIN_FILE_SIZE_LIMIT_BYTES:
        raise ValueError(f"file size limit must be at least {MIN_FILE_SIZE_LIMIT_BYTES} bytes")
    if free_disk_reserve_bytes < 0:
        raise ValueError("free disk reserve must not be negative")


class RecordingStorage:
    """Owns one resolved backend recording root and no-replace finalization."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        requested = Path(root).expanduser()
        if create:
            requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = requested.resolve(strict=True)
        if not resolved.is_dir():
            raise RecordingStorageError(errno.ENOTDIR, "recording root is not a directory", str(resolved))
        if not os.access(resolved, os.W_OK | os.X_OK):
            raise RecordingStorageError(errno.EACCES, "recording root is not writable", str(resolved))
        self.root = resolved

    def free_bytes(self) -> int:
        stat = os.statvfs(self.root)
        return stat.f_bavail * stat.f_frsize

    def ensure_free_reserve(self, reserve_bytes: int) -> int:
        available = self.free_bytes()
        if available <= reserve_bytes:
            raise RecordingStorageError(
                errno.ENOSPC,
                f"available space {available} is at or below reserve {reserve_bytes}",
                str(self.root),
            )
        return available

    def open_session(
        self,
        *,
        prefix: str,
        session_uuid: UUID,
        creation_unix_ns: int,
    ) -> StorageSession:
        validate_file_prefix(prefix)
        instant = datetime.fromtimestamp(creation_unix_ns / 1e9, tz=timezone.utc)
        timestamp = instant.strftime("%Y%m%dT%H%M%S.") + f"{creation_unix_ns % 1_000_000_000:09d}Z"
        basename = f"{prefix}_{timestamp}_{session_uuid.hex[:8]}.san90rta"
        final_path = self._inside_root(basename)
        part_path = self._inside_root(f"{basename}.part")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(part_path, flags, 0o600)
            os.fchmod(fd, 0o600)
        except OSError as error:
            raise RecordingStorageError(error.errno, f"create part file failed: {error}", str(part_path)) from error
        if os.fstat(fd).st_dev != os.stat(self.root).st_dev:
            os.close(fd)
            raise RecordingStorageError(errno.EXDEV, "part and final paths are not on the recording filesystem")
        return StorageSession(self.root, part_path, final_path, fd)

    def _inside_root(self, basename: str) -> Path:
        candidate = self.root / basename
        if candidate.parent.resolve(strict=True) != self.root:
            raise ValueError("recording path escapes configured root")
        return candidate

    def finalize(self, session: StorageSession, *, fsync_directory: bool = True) -> Path:
        if session.part_path.parent != self.root or session.final_path.parent != self.root:
            raise RecordingStorageError(errno.EXDEV, "finalization paths must be inside the recording root")
        renamed = False
        try:
            _rename_noreplace(session.part_path, session.final_path)
            renamed = True
            if fsync_directory:
                directory_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except OSError as error:
            if renamed and not session.part_path.exists():
                try:
                    os.link(session.final_path, session.part_path, follow_symlinks=False)
                except OSError:
                    pass
            raise RecordingStorageError(
                error.errno, f"atomic finalization failed: {error}", str(session.part_path)
            ) from error
        return session.final_path


def _rename_noreplace(source: Path, target: Path) -> None:
    """Use Linux renameat2, falling back to same-filesystem link/unlink."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is not None:
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(target),
            _RENAME_NOREPLACE,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number not in {errno.ENOSYS, errno.EINVAL}:
            raise OSError(error_number, os.strerror(error_number), str(target))
    os.link(source, target, follow_symlinks=False)
    try:
        os.unlink(source)
    except OSError:
        # The final path contains the complete file. Keep both names if unlink
        # fails rather than risking data loss.
        raise
