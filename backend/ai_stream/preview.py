"""Disk diagnostics and bounded in-memory browser preview support."""

from __future__ import annotations

import io
import json
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image

from .protocol import CaptureMetadata, IMAGE_HEIGHT, IMAGE_WIDTH, PAYLOAD_SIZE


@dataclass(frozen=True, slots=True)
class AiPreviewSnapshot:
    sequence: int
    source: str
    playback_epoch: int | None
    config_id: int | None
    configuration_generation: int
    center_frequency_hz: float
    frequency_start_hz: float
    frequency_stop_hz: float
    width: int
    height: int
    created_at_ns: int
    content_type: str
    image: bytes
    power_min_dbm: float | None = None
    power_max_dbm: float | None = None
    power_range_db: float | None = None
    db_per_gray_level: float | None = None
    power_range_generation: int | None = None

    def status(self) -> dict[str, object]:
        return {
            "available": True,
            "reason": None,
            "sequence": self.sequence,
            "source": self.source,
            "playback_epoch": self.playback_epoch,
            "config_id": self.config_id,
            "configuration_generation": self.configuration_generation,
            "power_min_dbm": self.power_min_dbm,
            "power_max_dbm": self.power_max_dbm,
            "power_range_db": self.power_range_db,
            "db_per_gray_level": self.db_per_gray_level,
            "power_range_generation": self.power_range_generation,
            "center_frequency_hz": self.center_frequency_hz,
            "frequency_start_hz": self.frequency_start_hz,
            "frequency_stop_hz": self.frequency_stop_hz,
            "width": self.width,
            "height": self.height,
            "created_at_ns": self.created_at_ns,
            "content_type": self.content_type,
        }


class LatestAiPreviewStore:
    """One immutable encoded frame; readers never observe mismatched metadata."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot: AiPreviewSnapshot | None = None
        self._reason = "waiting"

    def publish(self, snapshot: AiPreviewSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._reason = "waiting"

    def clear(self, reason: str = "waiting") -> None:
        with self._lock:
            self._snapshot = None
            self._reason = reason

    def snapshot(self) -> AiPreviewSnapshot | None:
        with self._lock:
            return self._snapshot

    def image_for_sequence(self, sequence: int) -> AiPreviewSnapshot | None:
        with self._lock:
            snapshot = self._snapshot
            return snapshot if snapshot is not None and snapshot.sequence == sequence else None

    def status(self, *, source: str) -> dict[str, object]:
        with self._lock:
            snapshot = self._snapshot
            reason = self._reason
        if snapshot is not None:
            return snapshot.status()
        return {
            "available": False,
            "reason": reason,
            "sequence": None,
            "source": source,
            "playback_epoch": None,
            "config_id": None,
            "configuration_generation": None,
            "power_min_dbm": None,
            "power_max_dbm": None,
            "power_range_db": None,
            "db_per_gray_level": None,
            "power_range_generation": None,
            "center_frequency_hz": None,
            "frequency_start_hz": None,
            "frequency_stop_hz": None,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "created_at_ns": None,
            "content_type": "image/png",
        }


@dataclass(frozen=True, slots=True)
class _PendingPreview:
    capture: CaptureMetadata
    gray8: bytes
    reset_token: int


class AiPreviewEncoder:
    """Newest-only PNG worker independent from acquisition and ZMQ cadence."""

    DEFAULT_VIEWER_LEASE_SECONDS = 1.5

    def __init__(
        self,
        store: LatestAiPreviewStore,
        *,
        maximum_fps: float = 2.0,
    ) -> None:
        if maximum_fps <= 0:
            raise ValueError("preview maximum_fps must be positive")
        self.store = store
        self.maximum_fps = maximum_fps
        self._period_ns = round(1e9 / maximum_fps)
        self._queue: queue.Queue[_PendingPreview] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_accepted_ns = 0
        self._viewer_lease_deadline_ns = 0
        self._reset_token = 0
        self._lock = Lock()
        self.submitted = 0
        self.encoded = 0
        self.dropped = 0
        self.skipped_without_viewer = 0
        self.last_encode_ms = 0.0
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="san90-ai-preview", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None
        self._drain()

    def submit(self, image: np.ndarray, capture: CaptureMetadata) -> bool:
        if image.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or image.dtype != np.uint8:
            raise ValueError("AI preview requires a 640x640 GRAY8 image")
        now_ns = time.monotonic_ns()
        with self._lock:
            # Check demand before taking the 409,600-byte ownership copy. The
            # external AI transport remains independent and continues at its
            # configured cadence when no browser preview is watching.
            if now_ns >= self._viewer_lease_deadline_ns:
                self.skipped_without_viewer += 1
                return False
            if now_ns - self._last_accepted_ns < self._period_ns:
                self.dropped += 1
                return False
            self._last_accepted_ns = now_ns
            self.submitted += 1
            reset_token = self._reset_token
        pending = _PendingPreview(capture, image.tobytes(order="C"), reset_token)
        try:
            self._queue.put_nowait(pending)
            return True
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            with self._lock:
                self.dropped += 1
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(pending)
            return True
        except queue.Full:
            with self._lock:
                self.dropped += 1
            return False

    def renew_viewer_lease(self, duration_seconds: float = DEFAULT_VIEWER_LEASE_SECONDS) -> None:
        """Keep preview encoding active briefly after a visible viewer poll."""
        if not np.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("preview viewer lease duration must be finite and positive")
        now_ns = time.monotonic_ns()
        with self._lock:
            was_active = now_ns < self._viewer_lease_deadline_ns
            self._viewer_lease_deadline_ns = now_ns + round(duration_seconds * 1e9)
            if not was_active:
                # Never show the cached image from a prior viewer session.
                self._reset_token += 1
                self._last_accepted_ns = 0
                self._drain()
                self.store.clear("waiting")

    def clear(self, reason: str = "waiting") -> None:
        with self._lock:
            self._reset_token += 1
        self._drain()
        self.store.clear(reason)

    def status_metrics(self) -> dict[str, object]:
        with self._lock:
            remaining_ns = max(0, self._viewer_lease_deadline_ns - time.monotonic_ns())
            return {
                "preview_maximum_fps": self.maximum_fps,
                "preview_viewer_lease_active": remaining_ns > 0,
                "preview_viewer_lease_remaining_ms": remaining_ns / 1e6,
                "preview_queue_depth": self._queue.qsize(),
                "preview_submitted_total": self.submitted,
                "preview_encoded_total": self.encoded,
                "preview_dropped_total": self.dropped,
                "preview_skipped_without_viewer_total": self.skipped_without_viewer,
                "preview_encode_time_ms": self.last_encode_ms,
                "preview_last_error": self.last_error,
            }

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                pending = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            started = time.perf_counter()
            try:
                encoded = io.BytesIO()
                Image.frombytes("L", (IMAGE_WIDTH, IMAGE_HEIGHT), pending.gray8).save(
                    encoded,
                    format="PNG",
                    optimize=False,
                    compress_level=3,
                )
                capture = pending.capture
                snapshot = AiPreviewSnapshot(
                    sequence=capture.sequence,
                    source=capture.preview_source,
                    playback_epoch=capture.playback_epoch,
                    config_id=capture.config_id,
                    configuration_generation=capture.configuration_generation,
                    power_min_dbm=capture.power_profile.min_dbm,
                    power_max_dbm=capture.power_profile.max_dbm,
                    power_range_db=capture.power_profile.max_dbm - capture.power_profile.min_dbm,
                    db_per_gray_level=capture.power_profile.db_per_gray_level,
                    power_range_generation=capture.power_profile.generation,
                    center_frequency_hz=capture.center_frequency_hz,
                    frequency_start_hz=capture.start_frequency_hz,
                    frequency_stop_hz=capture.stop_frequency_hz,
                    width=IMAGE_WIDTH,
                    height=IMAGE_HEIGHT,
                    created_at_ns=capture.capture_end_timestamp_ns,
                    content_type="image/png",
                    image=encoded.getvalue(),
                )
                with self._lock:
                    current = pending.reset_token == self._reset_token
                    if current:
                        self.encoded += 1
                        self.store.publish(snapshot)
                    else:
                        self.dropped += 1
                    self.last_error = None
                    self.last_encode_ms = (time.perf_counter() - started) * 1000.0
            except Exception as error:
                with self._lock:
                    self.last_error = str(error)

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


class PreviewWriter:
    def __init__(self, directory: Path, interval_seconds: float, max_files: int) -> None:
        self.directory = directory
        self.interval_seconds = interval_seconds
        self.max_files = max_files
        self._last_saved = 0.0
        self._latest_png: bytes | None = None
        self._lock = Lock()

    def maybe_save(self, image: np.ndarray, metadata: dict[str, Any]) -> tuple[bool, float]:
        now = time.monotonic()
        if now - self._last_saved < self.interval_seconds:
            return False, 0.0
        if image.shape != (640, 640) or image.dtype != np.uint8:
            raise ValueError("preview image must be 640x640 GRAY8")
        started = time.perf_counter()
        self.directory.mkdir(parents=True, exist_ok=True)
        center_mhz = float(metadata["center_frequency_hz"]) / 1e6
        stem = (
            f"san90_gray8_{int(metadata['sequence']):012d}_{metadata['power_profile']}_"
            f"{center_mhz:.3f}MHz_{int(metadata['timestamp_ns'])}"
        )
        png_path = self.directory / f"{stem}.png"
        json_path = self.directory / f"{stem}.json"
        pil_image = Image.fromarray(image, mode="L")
        encoded = io.BytesIO()
        pil_image.save(encoded, format="PNG")
        png_bytes = encoded.getvalue()
        png_path.write_bytes(png_bytes)
        json_path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with self._lock:
            self._latest_png = png_bytes
        self._last_saved = now
        self._rotate()
        return True, (time.perf_counter() - started) * 1000.0

    def latest_png(self) -> bytes | None:
        with self._lock:
            return self._latest_png

    def _rotate(self) -> None:
        images = sorted(self.directory.glob("san90_gray8_*.png"), key=lambda path: path.stat().st_mtime_ns)
        for path in images[:-self.max_files]:
            json_path = path.with_suffix(".json")
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            try:
                json_path.unlink()
            except FileNotFoundError:
                pass
