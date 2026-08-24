"""Playback adapter feeding the existing temporal-spectrum/waterfall exchanges."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import numpy as np

from backend.analyzer.base import AnalyzerSource
from backend.analyzer.models import (
    AnalyzerActualSettings,
    AnalyzerCapabilities,
    AnalyzerSettings,
    AnalyzerSettingsState,
    DeviceInfo,
    RuntimeStatus,
    SpectrumFrame,
    SpectrumTemporalFrame,
    WaterfallBatch,
)
from backend.analyzer.raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.spectrum_temporal import LatestSpectrumTemporalExchange, NativeSpectrumTemporalAccumulator
from backend.analyzer.waterfall import TimedWaterfallBatchProducer, WaterfallRateConfig
from backend.ai_stream.config import AiStreamConfig
from backend.ai_stream.pipeline import AiStreamPipeline
from backend.ai_stream.protocol import CaptureMetadata
from backend.recording.models import ConfigRecordFlags, ConfigurationRecord, TraceRecordFlags

from .models import IndexedTraceBatch


class PlaybackSource(AnalyzerSource):
    """No SDK ownership: the playback worker is the sole producer."""

    def __init__(self, *, waterfall_config: WaterfallRateConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._connected = False
        self._running = False
        self._config: ConfigurationRecord | None = None
        self._settings_state: AnalyzerSettingsState | None = None
        self._temporal: NativeSpectrumTemporalAccumulator | None = None
        self._temporal_exchange = LatestSpectrumTemporalExchange()
        self._waterfall_config = waterfall_config or WaterfallRateConfig(60.0, 60.0, 1)
        self._waterfall: TimedWaterfallBatchProducer | None = None
        self._received = 0
        self._published = 0
        self._started_ns: int | None = None
        self._last_timestamp_ns: int | None = None
        self._if_overflow = False
        self._activation_count = 0
        self._display_generation = 0
        self._playback_epoch = 0
        self._run_ai = False
        self._ai_outstanding: dict[int, tuple[int, int]] = {}
        self._ai_reset_counter = 0
        self._ai_pipeline = AiStreamPipeline(
            replace(AiStreamConfig.from_environment(), enabled=False),
            capture_callback=self._register_ai_capture,
            preview_source="playback",
        )

    @property
    def activation_count(self) -> int:
        with self._lock:
            return self._activation_count

    @property
    def has_config(self) -> bool:
        with self._lock:
            return self._config is not None

    def connect(self) -> None:
        with self._lock:
            self._connected = True

    def disconnect(self) -> None:
        self.stop()
        self._ai_pipeline.stop()
        with self._lock:
            self._run_ai = False
            self._ai_outstanding.clear()
            self._connected = False
            self._config = None
            self._settings_state = None
            self._temporal_exchange.clear()
            if self._waterfall is not None:
                self._waterfall.exchange.clear()

    def start(self) -> None:
        with self._lock:
            self._connected = True
            self._running = True
            self._started_ns = time.monotonic_ns()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    @staticmethod
    def _display_geometry_matches(
        previous: ConfigurationRecord,
        current: ConfigurationRecord,
    ) -> bool:
        """Return whether existing spectrum/waterfall history remains aligned."""
        return (
            previous.frame_width == current.frame_width
            and previous.start_frequency_hz == current.start_frequency_hz
            and previous.stop_frequency_hz == current.stop_frequency_hz
        )

    def activate_config(self, config: ConfigurationRecord, *, force: bool = False) -> None:
        with self._lock:
            previous = self._config
            if not force and previous is not None and previous.config_id == config.config_id:
                return
            geometry_changed = (
                force
                or previous is None
                or not self._display_geometry_matches(previous, config)
            )
            # CONFIG records also capture calibration/readback changes. Those
            # values must become active immediately, but they do not invalidate
            # frequency-aligned waterfall history. A display generation is
            # therefore advanced only for a timeline reset or geometry change.
            if geometry_changed:
                self._display_generation += 1
            display_generation = self._display_generation
            verified = config.metadata.get("verified", {}) if isinstance(config.metadata, dict) else {}
            flags = ConfigRecordFlags(config.prefix.flags)
            vbw = config.vbw_hz if flags & ConfigRecordFlags.VBW_VALID else None
            sweep = config.sweep_time_s if flags & ConfigRecordFlags.SWEEP_TIME_VALID else None
            requested = AnalyzerSettings(
                center_frequency_hz=config.center_frequency_hz,
                span_hz=config.span_hz,
                rbw_hz=config.rbw_hz,
                rbw_mode=str(verified.get("rbw_mode", "recorded")),
                vbw_hz=vbw,
                vbw_mode=str(verified.get("vbw_mode", "recorded")) if vbw is not None else None,
                reference_level_dbm=config.reference_level_dbm,
                attenuation_db=verified.get("attenuation_db"),
                preamplifier=verified.get("preamplifier"),
                gain_strategy=verified.get("gain_strategy"),
                if_agc_enabled=verified.get("if_agc_enabled"),
                sweep_time_s=sweep,
                window=verified.get("window"),
                detector=verified.get("detector"),
                amplitude_offset_db=config.software_amplitude_offset_db,
            )
            actual = AnalyzerActualSettings(
                center_frequency_hz=config.center_frequency_hz,
                start_frequency_hz=config.start_frequency_hz,
                stop_frequency_hz=config.stop_frequency_hz,
                span_hz=config.span_hz,
                reference_level_dbm=config.reference_level_dbm,
                attenuation_db=verified.get("attenuation_db"),
                attenuation_automatic=bool(verified.get("attenuation_automatic", False)),
                preamplifier=verified.get("preamplifier"),
                gain_strategy=verified.get("gain_strategy"),
                if_agc_enabled=verified.get("if_agc_enabled"),
                if_agc_target_dbfs=verified.get("if_agc_target_dbfs"),
                if_agc_period_s=verified.get("if_agc_period_s"),
                if_agc_gain_db=verified.get("if_agc_gain_db"),
                rbw_hz=config.rbw_hz,
                rbw_mode=str(verified.get("rbw_mode", "recorded")),
                vbw_hz=vbw,
                vbw_mode=str(verified.get("vbw_mode", "recorded")) if vbw is not None else None,
                sweep_time_mode="recorded",
                sweep_time_multiple=None,
                sweep_time_s=sweep,
                window=verified.get("window"),
                detector=verified.get("detector"),
                fft_size=config.fft_size,
                scale_to_dbm=config.hardware_scale_db_per_code,
                offset_to_dbm=config.hardware_offset_dbm,
                point_count=config.frame_width,
                frequency_bin_spacing_hz=config.span_hz / config.frame_width,
                amplitude_offset_db=config.software_amplitude_offset_db,
            )
            self._settings_state = AnalyzerSettingsState(requested, actual, display_generation)
            dimensions_changed = previous is None or previous.frame_width != config.frame_width
            if dimensions_changed:
                self._temporal = NativeSpectrumTemporalAccumulator(config.frame_width)
                self._waterfall = TimedWaterfallBatchProducer(
                    config.frame_width, display_generation, self._waterfall_config
                )
            elif geometry_changed:
                assert self._temporal is not None and self._waterfall is not None
                self._temporal.reset(generation=display_generation)
                self._temporal_exchange.clear()
                self._waterfall.reconfigure(
                    config.frame_width, display_generation, self._waterfall_config
                )
            self._config = config
            self._activation_count += 1
            self._ai_pipeline.set_preview_context(
                source="playback",
                playback_epoch=self._playback_epoch,
                config_id=config.config_id,
            )
            self._ai_pipeline.clear_preview("waiting")
            self._clear_ai_locked()

    def reset_timeline(self, epoch: int, config: ConfigurationRecord) -> None:
        """Shared seek/step/loop reset; exchanges are cleared before target output."""
        with self._lock:
            self._playback_epoch = epoch
            self._temporal_exchange.clear()
            if self._waterfall is not None:
                self._waterfall.exchange.clear()
            self.activate_config(config, force=True)

    def consume_batch(self, batch: IndexedTraceBatch, payload: bytes, *, feed_ai: bool = True) -> None:
        with self._lock:
            if not self._running or self._config is None:
                raise RuntimeError("playback source is not running/configured")
            config = self._config
            if batch.config_id != config.config_id:
                raise RuntimeError("CONFIG must activate before TRACE")
            traces = np.frombuffer(payload, dtype=np.uint8).reshape(batch.trace_count, batch.frame_width)
            now_mono = time.monotonic_ns()
            now_unix = time.time_ns()
            # Store native and software offsets separately on disk; combine once
            # here because RawAmplitudeMapping performs the only dBm conversion.
            mapping = RawAmplitudeMapping(
                config.hardware_scale_db_per_code,
                config.hardware_offset_dbm + config.software_amplitude_offset_db,
            )
            metadata = RawTraceMetadata(
                sequence=batch.first_sequence + batch.trace_count - 1,
                device_timestamp_ns=batch.device_packet_timestamp_ns,
                host_timestamp_ns=now_unix,
                receipt_monotonic_ns=now_mono,
                start_frequency_hz=config.start_frequency_hz,
                center_frequency_hz=config.center_frequency_hz,
                stop_frequency_hz=config.stop_frequency_hz,
                span_hz=config.span_hz,
                rbw_hz=config.rbw_hz,
                reference_level_dbm=config.reference_level_dbm,
                mapping=mapping,
                configuration_generation=self._display_generation,
            )
            assert self._temporal is not None and self._waterfall is not None
            temporal = self._temporal.add_packet(traces, metadata)
            if temporal is not None:
                self._temporal_exchange.publish(temporal)
                self._published += 1
            self._waterfall.add_packet(
                traces,
                metadata,
                trace_timestamp_step_ns=batch.nominal_trace_period_ns,
            )
            if self._run_ai and feed_ai:
                self._ai_pipeline.offer_packet(
                    traces,
                    metadata,
                    trace_timestamp_step_ns=batch.nominal_trace_period_ns,
                )
            self._received += batch.trace_count
            self._last_timestamp_ns = batch.host_receipt_unix_ns
            self._if_overflow = bool(batch.trace_flags & int(TraceRecordFlags.SDK_IF_OVERFLOW | TraceRecordFlags.IF_OVERFLOW_LATCHED))

    def flush(self) -> None:
        with self._lock:
            if self._temporal is not None:
                frame = self._temporal.flush(time.monotonic_ns())
                if frame is not None:
                    self._temporal_exchange.publish(frame)
                    self._published += 1

    def set_run_ai(self, enabled: bool) -> None:
        with self._lock:
            if enabled == self._run_ai:
                return
            self._clear_ai_locked()
            self._ai_pipeline.set_enabled(enabled)
            if enabled:
                status = self._ai_pipeline.status()
                if not status.get("bound", False):
                    self._ai_pipeline.set_enabled(False)
                    raise RuntimeError(str(status.get("last_error") or "AI image publisher could not bind"))
            self._run_ai = enabled

    def ai_preview_status(self, *, viewer: bool = False) -> dict[str, object]:
        status = self._ai_pipeline.preview_status(viewer=viewer and self._run_ai)
        if not self._run_ai:
            return {**status, "available": False, "reason": "playback_ai_disabled"}
        return status

    def ai_preview_image(self, sequence: int):
        return self._ai_pipeline.preview_image(sequence) if self._run_ai else None

    def clear_ai_preview(self, reason: str = "waiting") -> None:
        self._ai_pipeline.clear_preview(reason)

    def ai_status(self) -> dict[str, object]:
        return {"run_ai": self._run_ai, **self._ai_pipeline.status()}

    def set_ai_power_range(self, low_dbm: float, high_dbm: float, generation: int) -> dict[str, object]:
        self._ai_pipeline.set_power_range(low_dbm, high_dbm, generation=generation)
        return self.ai_status()

    def accept_ai_result(self, result: dict[str, object]) -> dict[str, object] | None:
        sequence = result.get("sequence")
        if not isinstance(sequence, int):
            return None
        with self._lock:
            if not self._run_ai:
                return None
            correlation = self._ai_outstanding.pop(sequence, None)
            if correlation is None or self._config is None:
                return None
            epoch, config_id = correlation
            if epoch != self._playback_epoch or config_id != self._config.config_id:
                return None
            return {
                **result,
                "source": "playback",
                "playback_epoch": epoch,
                "configuration_generation": self._display_generation,
            }

    def _register_ai_capture(self, capture: CaptureMetadata) -> None:
        with self._lock:
            if not self._run_ai or self._config is None:
                return
            self._ai_outstanding[capture.sequence] = (self._playback_epoch, self._config.config_id)
            while len(self._ai_outstanding) > 256:
                self._ai_outstanding.pop(next(iter(self._ai_outstanding)))

    def _clear_ai_locked(self) -> None:
        self._ai_outstanding.clear()
        self._ai_reset_counter += 1
        namespace = self._playback_epoch * 65_536 + (self._ai_reset_counter & 0xFFFF)
        self._ai_pipeline.reset_timeline(namespace)

    def read_spectrum_temporal(self) -> SpectrumTemporalFrame | None:
        return self._temporal_exchange.take()

    def read_waterfall_batch(self) -> WaterfallBatch | None:
        with self._lock:
            return None if self._waterfall is None else self._waterfall.exchange.take_latest()

    def get_spectrum_temporal_metrics(self) -> dict[str, float | int]:
        with self._lock:
            temporal = self._temporal
            return {
                "completed_intervals": 0 if temporal is None else temporal.completed_intervals,
                "total_traces_integrated": 0 if temporal is None else temporal.total_traces_integrated,
            }

    def get_capabilities(self) -> AnalyzerCapabilities:
        state = self.get_settings_state()
        return AnalyzerCapabilities(
            source="playback",
            measurement_modes=("rta",),
            supported_controls=frozenset(),
            native_point_counts=(state.actual.point_count,),
        )

    def get_settings(self) -> AnalyzerSettings:
        return replace(self.get_settings_state().requested)

    def apply_settings(self, settings: AnalyzerSettings) -> AnalyzerSettings:
        raise RuntimeError("playback configuration is read-only")

    def apply_amplitude_offset(self, amplitude_offset_db: float) -> float:
        raise RuntimeError("playback amplitude mapping is read-only")

    def get_settings_state(self) -> AnalyzerSettingsState:
        with self._lock:
            if self._settings_state is None:
                raise RuntimeError("playback has no active CONFIG")
            return self._settings_state

    def read_frame(self) -> SpectrumFrame | None:
        return None

    def get_status(self) -> RuntimeStatus:
        with self._lock:
            elapsed = 0.0 if self._started_ns is None else (time.monotonic_ns() - self._started_ns) / 1e9
            config = self._config
            return RuntimeStatus(
                source="playback",
                connected=self._connected,
                acquisition_running=self._running,
                if_overflow=self._if_overflow,
                amplitude_offset_db=0.0 if config is None else config.software_amplitude_offset_db,
                sdk_frames_received=self._received,
                display_frames_published=self._published,
                last_frame_timestamp_ns=self._last_timestamp_ns,
                sdk_frames_per_second=self._received / elapsed if elapsed > 0 else 0.0,
                point_count=None if config is None else config.frame_width,
                configuration_generation=self._display_generation,
            )

    def get_device_info(self) -> DeviceInfo | None:
        return DeviceInfo(source="playback", model="SAN-90 recording", serial="PLAYBACK")

    def get_spectrum_publish_fps(self) -> float:
        return 60.0
