"""Spawns and supervises tools/yolo_detection.py as a child of the backend
process, so a single backend start also brings up AI detection instead of
requiring it to be launched by hand (see run_all_services.md)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger("san90.ai_detector_process")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCRIPT = PROJECT_ROOT / "tools" / "yolo_detection.py"
DEFAULT_MODEL = PROJECT_ROOT / "ai_detect" / "weights" / "best_openvino_model"
DEFAULT_LOG_PATH = PROJECT_ROOT / ".run" / "ai_detector.log"

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


class AiDetectorProcessManager:
    """Owns the yolo_detection.py child process across the backend's lifespan."""

    def __init__(self) -> None:
        self.enabled = _enabled("AI_DETECTOR_ENABLED")
        self.script = Path(os.getenv("AI_DETECTOR_SCRIPT", str(DEFAULT_SCRIPT)))
        self.model = os.getenv("AI_DETECTOR_MODEL", str(DEFAULT_MODEL))
        self.connect_url = os.getenv("AI_DETECTOR_CONNECT", "tcp://127.0.0.1:5557")
        self.publish_url = os.getenv("AI_DETECTOR_PUBLISH", "tcp://127.0.0.1:5558")
        self.review_publish_url = os.getenv("AI_DETECTOR_REVIEW_PUBLISH", "tcp://127.0.0.1:5555")
        self.confidence = os.getenv("AI_DETECTOR_CONF", "0.5")
        self.log_path = Path(os.getenv("AI_DETECTOR_LOG", str(DEFAULT_LOG_PATH)))
        self._process: asyncio.subprocess.Process | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._log_file = None
        self._stopping = False

    async def start(self) -> None:
        if not self.enabled:
            logger.info("AI detector integration disabled (AI_DETECTOR_ENABLED=false)")
            return
        if self._process is not None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self.log_path, "ab")
        self._stopping = False
        args = [
            sys.executable,
            str(self.script),
            "--connect", self.connect_url,
            "--model", self.model,
            "--conf", self.confidence,
            "--publish", self.publish_url,
            "--review-publish", self.review_publish_url,
        ]
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(PROJECT_ROOT),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=self._log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            logger.error("Failed to launch AI detector: %s", error)
            self._log_file.close()
            self._log_file = None
            return
        logger.info("AI detector started (PID %s). Log: %s", self._process.pid, self.log_path)
        self._monitor_task = asyncio.create_task(self._monitor(), name="ai-detector-monitor")

    async def _monitor(self) -> None:
        process = self._process
        if process is None:
            return
        return_code = await process.wait()
        if not self._stopping:
            logger.warning(
                "AI detector exited unexpectedly (code %s); see %s. It will not be restarted automatically.",
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
            logger.info("AI detector stopped (exit code %s)", process.returncode)
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
