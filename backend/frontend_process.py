"""Spawns and supervises the Vite frontend dev server as a child of the
backend process, so a single backend start also brings up the web UI instead
of requiring `npm run frontend:start` as a separate step."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
from pathlib import Path

logger = logging.getLogger("san90.frontend_process")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VITE_BIN = PROJECT_ROOT / "node_modules" / ".bin" / "vite"
DEFAULT_LOG_PATH = PROJECT_ROOT / ".run" / "frontend.log"

SIGINT_GRACE_S = 3.0
SIGTERM_GRACE_S = 2.0


def _enabled(name: str, default: bool = True) -> bool:
    text = os.getenv(name)
    if text is None:
        return default
    normalized = text.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


class FrontendProcessManager:
    """Owns the Vite dev server child process across the backend's lifespan."""

    def __init__(self) -> None:
        self.enabled = _enabled("FRONTEND_ENABLED")
        self.host = os.getenv("FRONTEND_HOST", "0.0.0.0")
        self.port = os.getenv("FRONTEND_PORT", "5173")
        self.vite_bin = Path(os.getenv("FRONTEND_VITE_BIN", str(DEFAULT_VITE_BIN)))
        self.log_path = Path(os.getenv("FRONTEND_LOG", str(DEFAULT_LOG_PATH)))
        self._process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._log_file = None
        self._stopping = False

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Frontend integration disabled (FRONTEND_ENABLED=false)")
            return
        if self._process is not None:
            return
        node_path = shutil.which("node")
        if node_path is None:
            logger.error("Cannot start frontend: no 'node' executable found on PATH")
            return
        if not self.vite_bin.exists():
            logger.error("Cannot start frontend: vite binary not found at %s (run 'npm install')", self.vite_bin)
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self.log_path, "ab")
        self._stopping = False
        args = [node_path, str(self.vite_bin), "--host", self.host, "--port", self.port]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(PROJECT_ROOT),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=self._log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            logger.error("Failed to launch frontend dev server: %s", error)
            self._log_file.close()
            self._log_file = None
            return
        logger.info(
            "Frontend dev server started (PID %s) at http://%s:%s. Log: %s",
            self._process.pid, self.host, self.port, self.log_path,
        )
        self._monitor_task = asyncio.create_task(self._monitor(), name="frontend-monitor")

    async def _monitor(self) -> None:
        process = self._process
        if process is None:
            return
        return_code = await process.wait()
        if not self._stopping:
            logger.warning(
                "Frontend dev server exited unexpectedly (code %s); see %s. It will not be restarted automatically.",
                return_code, self.log_path,
            )

    async def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process is not None and process.returncode is None:
            process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(process.wait(), timeout=SIGINT_GRACE_S)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=SIGTERM_GRACE_S)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            logger.info("Frontend dev server stopped (exit code %s)", process.returncode)
        monitor_task = self._monitor_task
        self._monitor_task = None
        if monitor_task is not None:
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
        self._process = None
