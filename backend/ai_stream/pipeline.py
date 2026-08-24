"""Facade joining acquisition-thread accumulation to the publisher worker."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import numpy as np

from backend.analyzer.raw_buffers import RawTraceMetadata

from .config import AiStreamConfig
from .image_accumulator import AiImageAccumulator
from .image_publisher import AiImagePublisher
from .metrics import AiStreamMetrics
from .power_profiles import PowerProfile, require_power_profile
from .protocol import CaptureMetadata


logger = logging.getLogger("san90.ai_stream")


class AiStreamPipeline:
    def __init__(
        self,
        config: AiStreamConfig | None = None,
        *,
        capture_callback: Callable[[CaptureMetadata], None] | None = None,
        preview_source: str = "hardware",
    ) -> None:
        self.config = config or AiStreamConfig.from_environment()
        self.metrics = AiStreamMetrics()
        self._profile_lock = threading.Lock()
        self._profile = require_power_profile(self.config.power_profile)
        self._enabled = self.config.enabled
        self._preview_context_lock = threading.Lock()
        self._preview_source = preview_source
        self._playback_epoch: int | None = None
        self._config_id: int | None = None
        self._preview_generation: int | None = None
        self.accumulator = AiImageAccumulator(
            target_images_per_second=self.config.target_images_per_second,
            queue_size=self.config.queue_size,
            buffer_pool_size=self.config.buffer_pool_size,
            profile_provider=self._current_profile,
            metrics=self.metrics,
            capture_callback=capture_callback,
            preview_context_provider=self._preview_context,
        )
        self.accumulator.set_enabled(self._enabled)
        self.publisher = AiImagePublisher(self.config, self.accumulator, self.metrics)
        self._last_ingest_error_log = 0.0

    def start(self) -> None:
        if self._enabled:
            self.publisher.start()

    def stop(self) -> None:
        self.accumulator.set_enabled(False)
        self.publisher.stop()
        self.accumulator.drain()
        self.clear_preview("disabled")

    def configure(self, packet_frames: int, frame_width: int, generation: int) -> None:
        self.accumulator.configure(packet_frames, frame_width, generation)

    def offer_packet(self, raw: np.ndarray, metadata: RawTraceMetadata, *, trace_timestamp_step_ns: int) -> None:
        if self._enabled:
            try:
                if metadata.configuration_generation != self._preview_generation:
                    self._preview_generation = metadata.configuration_generation
                    self.clear_preview("waiting")
                self.accumulator.offer_packet(raw, metadata, trace_timestamp_step_ns=trace_timestamp_step_ns)
            # This is the fault boundary protecting the sole SDK acquisition
            # loop. Failures are counted and rate-limited in logs, never hidden.
            except Exception as error:
                self.metrics.update_latest(last_error=str(error))
                now = time.monotonic()
                if now - self._last_ingest_error_log >= self.config.recurring_log_interval_seconds:
                    logger.error("AI packet branch dropped data without stopping acquisition: %s", error)
                    self._last_ingest_error_log = now

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self.accumulator.set_enabled(enabled)
        if enabled:
            self.publisher.start()
        else:
            self.publisher.stop()
            self.accumulator.drain()
            self.clear_preview("disabled")

    def start_publisher(self) -> None:
        self.publisher.start()

    def stop_publisher(self) -> None:
        self.publisher.stop()
        self.accumulator.drain()

    def set_accepting(self, enabled: bool) -> None:
        """Change acquisition acceptance on the single SDK owner thread."""
        self._enabled = enabled
        self.accumulator.set_enabled(enabled)

    def set_power_profile(self, name: str) -> PowerProfile:
        profile = require_power_profile(name)
        return self.set_power_range(profile.min_dbm, profile.max_dbm, generation=profile.generation)

    def set_power_range(self, low_dbm: float, high_dbm: float, *, generation: int) -> PowerProfile:
        from .power_range import validate_power_range

        snapshot = validate_power_range(low_dbm, high_dbm, generation=generation)
        profile = snapshot.as_profile()
        with self._profile_lock:
            self._profile = profile
        self.clear_preview("power_range_changed")
        return profile

    def reset_timeline(self, sequence_namespace: int = 0) -> None:
        self.accumulator.reset_timeline(sequence_namespace)
        self.clear_preview("waiting")

    def set_preview_context(
        self,
        *,
        source: str | None = None,
        playback_epoch: int | None = None,
        config_id: int | None = None,
    ) -> None:
        with self._preview_context_lock:
            if source is not None:
                self._preview_source = source
            self._playback_epoch = playback_epoch
            self._config_id = config_id

    def _preview_context(self) -> tuple[str, int | None, int | None]:
        with self._preview_context_lock:
            return self._preview_source, self._playback_epoch, self._config_id

    def clear_preview(self, reason: str = "waiting") -> None:
        self.publisher.preview_encoder.clear(reason)

    def preview_status(self, *, viewer: bool = False) -> dict[str, object]:
        if viewer:
            self.publisher.preview_encoder.renew_viewer_lease()
        source, _, _ = self._preview_context()
        return {
            **self.publisher.preview_store.status(source=source),
            **self.publisher.preview_encoder.status_metrics(),
        }

    def preview_image(self, sequence: int):
        return self.publisher.preview_store.image_for_sequence(sequence)

    def _current_profile(self) -> PowerProfile:
        with self._profile_lock:
            return self._profile

    def status(self) -> dict[str, object]:
        profile = self._current_profile()
        return {
            "enabled": self._enabled,
            "bound": self.publisher.bound,
            "connected_or_sending": self.publisher.connected_or_sending,
            "active_power_profile": profile.name,
            "power_min_dbm": profile.min_dbm,
            "power_max_dbm": profile.max_dbm,
            "power_range_generation": profile.generation,
            "target_images_per_second": self.config.target_images_per_second,
            "image_width": 640,
            "image_height": 640,
            "pixel_format": "GRAY8",
            "payload_size_bytes": 409600,
            "bind": self.config.bind,
            **self.publisher.preview_encoder.status_metrics(),
            **self.metrics.snapshot(
                queue_depth=self.accumulator.queue_depth,
                free_buffer_count=self.accumulator.free_buffer_count,
            ),
        }

    def latest_preview_png(self) -> bytes | None:
        return self.publisher.latest_preview_png()
