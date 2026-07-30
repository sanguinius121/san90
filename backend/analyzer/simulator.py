"""Threaded analyzer simulator implementing the physical-source contract."""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from backend.recording.models import RecordingConfiguration, RecordingPacket

from .amplitude_correction import (
    AMPLITUDE_OFFSET_MAX_DB,
    AMPLITUDE_OFFSET_MIN_DB,
    AMPLITUDE_OFFSET_STEP_DB,
    validate_amplitude_offset,
)
from .base import AnalyzerSource
from .buffers import IntervalMaxHoldBuffer, LatestFrameBuffer
from .control_mapping import DETECTOR_VALUES, RBW_MODE_VALUES, WINDOW_VALUES
from .errors import AnalyzerConfigurationError, AnalyzerStateError
from .if_agc import (
    IF_AGC_PERIOD_MAX_S,
    IF_AGC_PERIOD_MIN_S,
    IF_AGC_PERIOD_UI_STEP_S,
    IF_AGC_TARGET_MAX_DBFS,
    IF_AGC_TARGET_MIN_DBFS,
    IF_AGC_TARGET_UI_STEP_DB,
    validate_if_agc_period,
    validate_if_agc_target,
)
from .models import (
    AnalyzerCapabilities,
    AnalyzerActualSettings,
    AnalyzerSettings,
    AnalyzerSettingsState,
    DeviceInfo,
    FrameType,
    NumericRange,
    RuntimeStatus,
    SpectrumFrame,
    SpectrumTemporalFrame,
    WaterfallBatch,
)
from .raw_buffers import RawAmplitudeMapping, RawTraceMetadata
from .spectrum_temporal import LatestSpectrumTemporalExchange, NativeSpectrumTemporalAccumulator
from .tradeoff import SAN90_RESOLUTION_TRADEOFF_STEPS, match_actual_tradeoff_step
from .sweep_time import (
    SWEEP_TIME_FIXED_MULTIPLES,
    SWEEP_TIME_MODE_VALUES,
    validate_manual_sweep_time,
    validate_sweep_time_mode,
    validate_sweep_time_multiple,
)
from .waterfall import TimedWaterfallBatchProducer, WaterfallProducerMetrics, WaterfallRateConfig
from .vbw import VBW_FIXED_MODE, VBW_MODE_RATIOS, validate_fixed_vbw_mode

if TYPE_CHECKING:
    from backend.recording.recorder import San90RtaRecorder


class SimulatorSource(AnalyzerSource):
    def __init__(
        self,
        *,
        point_count: int = 3328,
        frame_rate_hz: float = 60.0,
        seed: int | None = None,
        simulate_if_overflow: bool | None = None,
    ) -> None:
        if point_count < 16 or frame_rate_hz <= 0:
            raise ValueError("point_count must be >= 16 and frame_rate_hz must be positive")
        self._point_count = point_count
        self._native_point_count = point_count
        self._minimum_frame_rate_hz = frame_rate_hz
        self._frame_rate_hz = frame_rate_hz
        self._rng = np.random.default_rng(seed)
        self._settings = AnalyzerSettings(
            mode="rta",
            center_frequency_hz=2.45e9,
            span_hz=101.5625e6,
            rbw_hz=60.306e3,
            vbw_hz=6.030609e3,
            vbw_mode="ratio-0.1",
            reference_level_dbm=-10.0,
            attenuation_db=0,
            preamplifier="auto",
            gain_strategy="low-noise",
            if_agc_enabled=True,
            if_agc_target_dbfs=-9.0,
            if_agc_period_s=0.0,
            sweep_time_mode="minimum",
            sweep_time_multiple=3.0,
            sweep_time_s=1.0 / frame_rate_hz,
            window="blackman-nuttall",
            detector="positive-peak",
        )
        self._requested_settings = replace(self._settings)
        self._configuration_generation = 1
        self._latest = LatestFrameBuffer()
        self._max_hold = IntervalMaxHoldBuffer()
        self._spectrum_temporal = NativeSpectrumTemporalAccumulator(point_count)
        self._spectrum_temporal_exchange = LatestSpectrumTemporalExchange()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._sequence = 0
        self._phase = 0.0
        self._received = 0
        self._published = 0
        self._started_ns: int | None = None
        self._last_frame_ns: int | None = None
        self._if_agc_gain_db: float | None = 6.0
        self._simulate_if_overflow = (
            os.getenv("SIMULATOR_IF_OVERFLOW", "").strip().lower() in {"1", "true", "yes", "on"}
            if simulate_if_overflow is None
            else simulate_if_overflow
        )
        self._waterfall_config = WaterfallRateConfig(60.0, 60.0, 1)
        self._waterfall = TimedWaterfallBatchProducer(
            self._point_count, self._configuration_generation, self._waterfall_config
        )
        self._recording_sink: San90RtaRecorder | None = None
        # Import lazily to keep the analyzer factory independent from the AI
        # pipeline's RawTraceMetadata import during module initialization.
        from backend.ai_stream.config import AiStreamConfig
        from backend.ai_stream.pipeline import AiStreamPipeline
        self._ai_stream = AiStreamPipeline(AiStreamConfig.from_environment(), preview_source="simulator")
        self._frame_rate_hz = max(self._minimum_frame_rate_hz, self._waterfall_config.rows_per_second * 4.0)

    def connect(self) -> None:
        with self._lock:
            self._connected = True
        self._ai_stream.start()

    def disconnect(self) -> None:
        self.stop()
        self._ai_stream.stop()
        with self._lock:
            self._connected = False
            recording_sink = self._recording_sink
        if recording_sink is not None:
            recording_sink.source_disconnected()

    def set_recording_sink(self, recorder: San90RtaRecorder | None) -> None:
        """Attach an optional bounded recorder without changing realtime consumers."""
        with self._lock:
            self._recording_sink = recorder

    def get_ai_stream_status(self) -> dict[str, object]:
        return self._ai_stream.status()

    def set_ai_stream_enabled(self, enabled: bool) -> dict[str, object]:
        self._ai_stream.set_enabled(enabled)
        return self._ai_stream.status()

    def set_ai_power_profile(self, name: str) -> dict[str, object]:
        self._ai_stream.set_power_profile(name)
        return self._ai_stream.status()

    def ai_preview_status(self, *, viewer: bool = False) -> dict[str, object]:
        return self._ai_stream.preview_status(viewer=viewer)

    def ai_preview_image(self, sequence: int):
        return self._ai_stream.preview_image(sequence)

    def clear_ai_preview(self, reason: str = "waiting") -> None:
        self._ai_stream.clear_preview(reason)

    def start(self) -> None:
        with self._lock:
            if not self._connected:
                raise AnalyzerStateError("Simulator must be connected before acquisition starts")
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._started_ns = time.monotonic_ns()
            self._thread = threading.Thread(target=self._run, name="analyzer-simulator", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise AnalyzerStateError("Simulator acquisition thread did not stop")
        with self._lock:
            self._thread = None

    def get_capabilities(self) -> AnalyzerCapabilities:
        return AnalyzerCapabilities(
            source="simulator",
            measurement_modes=("rta",),
            supported_controls=frozenset({
                "center_frequency_hz", "span_hz", "rbw_hz", "rbw_mode",
                "reference_level_dbm", "attenuation_db", "preamplifier",
                "gain_strategy", "if_agc_enabled", "if_agc_target_dbfs", "if_agc_period_s",
                "window", "detector",
                "resolution_tradeoff_index", "amplitude_offset_db",
            }),
            numeric_ranges={
                "center_frequency_hz": NumericRange(1e6, 9.5e9),
                "span_hz": NumericRange(1e5, 9e9),
                "reference_level_dbm": NumericRange(-80.0, 20.0, 1.0),
                "amplitude_offset_db": NumericRange(
                    AMPLITUDE_OFFSET_MIN_DB,
                    AMPLITUDE_OFFSET_MAX_DB,
                    AMPLITUDE_OFFSET_STEP_DB,
                ),
                "if_agc_target_dbfs": NumericRange(
                    IF_AGC_TARGET_MIN_DBFS,
                    IF_AGC_TARGET_MAX_DBFS,
                    IF_AGC_TARGET_UI_STEP_DB,
                ),
                "if_agc_period_s": NumericRange(
                    IF_AGC_PERIOD_MIN_S,
                    IF_AGC_PERIOD_MAX_S,
                    IF_AGC_PERIOD_UI_STEP_S,
                ),
            },
            enum_values={},
            native_point_counts=tuple(step.point_count for step in SAN90_RESOLUTION_TRADEOFF_STEPS),
            supports_density=False,
            center_frequency_min_hz=1e6,
            center_frequency_max_hz=9.5e9,
            center_frequency_step_hz=1.0,
            reference_level_min_dbm=-80.0,
            reference_level_max_dbm=20.0,
            reference_level_step_db=1.0,
            supported_attenuation_values_db=tuple(range(0, 61)),
            supports_automatic_attenuation=True,
            preamplifier_modes=("auto", "off", "low", "medium", "high"),
            gain_strategy_modes=("low-noise", "high-linearity"),
            supports_live_frequency_change=True,
            supports_live_amplitude_change=True,
            requires_restart_for_frequency=False,
            requires_restart_for_amplitude=False,
            supports_rbw_control=True,
            rbw_control_mode="auto-or-manual-numeric",
            supported_rbw_values_hz=tuple(step.actual_rbw_hz for step in SAN90_RESOLUTION_TRADEOFF_STEPS),
            rbw_min_hz=100.0,
            rbw_max_hz=10_000_000.0,
            rbw_is_discrete=False,
            rbw_is_profile_based=False,
            rbw_changes_point_count=True,
            rbw_changes_span=False,
            rbw_requires_restart=False,
            window_modes=tuple(WINDOW_VALUES),
            detector_modes=tuple(DETECTOR_VALUES),
            window_requires_restart=False,
            detector_requires_restart=False,
            supports_resolution_tradeoff=True,
            resolution_tradeoff_steps=SAN90_RESOLUTION_TRADEOFF_STEPS,
            resolution_tradeoff_min_index=0,
            resolution_tradeoff_max_index=len(SAN90_RESOLUTION_TRADEOFF_STEPS) - 1,
            resolution_tradeoff_direction={"left": "time", "right": "frequency"},
            default_resolution_tradeoff_index=5,
            supports_auto_rbw=True,
        )

    def get_settings(self) -> AnalyzerSettings:
        with self._lock:
            return replace(self._settings)

    def apply_settings(self, settings: AnalyzerSettings) -> AnalyzerSettings:
        validate_amplitude_offset(settings.amplitude_offset_db)
        validate_if_agc_target(settings.if_agc_target_dbfs)
        validate_if_agc_period(settings.if_agc_period_s)
        if settings.mode != "rta":
            raise AnalyzerConfigurationError("Simulator currently supports only rta mode")
        if settings.center_frequency_hz <= 0:
            raise AnalyzerConfigurationError("center_frequency_hz must be positive")
        if settings.span_hz is None or settings.span_hz <= 0:
            raise AnalyzerConfigurationError("span_hz must be positive")
        if settings.rbw_mode not in RBW_MODE_VALUES:
            raise AnalyzerConfigurationError("unsupported simulator RBW mode")
        if settings.rbw_mode == "manual" and settings.rbw_hz is None:
            raise AnalyzerConfigurationError("manual RBW mode requires rbw_hz")
        if settings.rbw_hz is not None and settings.rbw_hz <= 0:
            raise AnalyzerConfigurationError("rbw_hz must be positive")
        validate_fixed_vbw_mode(settings.vbw_mode)
        validate_sweep_time_mode(settings.sweep_time_mode)
        if settings.sweep_time_mode == "custom-multiple":
            validate_sweep_time_multiple(settings.sweep_time_multiple)
        elif settings.sweep_time_mode == "manual":
            validate_manual_sweep_time(settings.sweep_time_s)
        if not -80 <= settings.reference_level_dbm <= 20:
            raise AnalyzerConfigurationError("reference_level_dbm is outside simulator capabilities")
        if settings.attenuation_db is not None and not 0 <= settings.attenuation_db <= 60:
            raise AnalyzerConfigurationError("attenuation_db is outside simulator capabilities")
        if settings.preamplifier not in {"auto", "off", "low", "medium", "high"}:
            raise AnalyzerConfigurationError("unsupported simulator preamplifier mode")
        if settings.gain_strategy not in {"low-noise", "high-linearity"}:
            raise AnalyzerConfigurationError("unsupported simulator gain strategy")
        if settings.window not in WINDOW_VALUES:
            raise AnalyzerConfigurationError("unsupported simulator window")
        if settings.detector not in DETECTOR_VALUES:
            raise AnalyzerConfigurationError("unsupported simulator detector")
        with self._lock:
            self._requested_settings = replace(settings)
            selected_step = None
            if settings.rbw_mode == "manual":
                selected_step = next((
                    step for step in SAN90_RESOLUTION_TRADEOFF_STEPS
                    if math.isclose(float(settings.rbw_hz or 0.0), step.requested_rbw_hz, rel_tol=0, abs_tol=0.5)
                ), None)
            actual_rbw = 60_306.09130859375 if settings.rbw_mode == "auto" else (
                selected_step.actual_rbw_hz if selected_step is not None else float(settings.rbw_hz or 60_306.09130859375)
            )
            self._point_count = (
                self._native_point_count if settings.rbw_mode == "auto" else
                selected_step.point_count if selected_step is not None else
                self._native_point_count if actual_rbw < 200_000 else max(16, self._native_point_count // 2)
            )
            actual_vbw = actual_rbw * VBW_MODE_RATIOS[VBW_FIXED_MODE]
            minimum_sweep_s = 1.0 / max(self._minimum_frame_rate_hz, 1.0)
            if settings.sweep_time_mode == "manual":
                actual_sweep_s = max(minimum_sweep_s, validate_manual_sweep_time(settings.sweep_time_s))
                actual_multiple = actual_sweep_s / minimum_sweep_s
            elif settings.sweep_time_mode == "custom-multiple":
                actual_multiple = validate_sweep_time_multiple(settings.sweep_time_multiple)
                actual_sweep_s = minimum_sweep_s * actual_multiple
            else:
                actual_multiple = SWEEP_TIME_FIXED_MULTIPLES[settings.sweep_time_mode]
                actual_sweep_s = minimum_sweep_s * actual_multiple
            self._settings = replace(
                settings,
                rbw_hz=actual_rbw,
                vbw_hz=actual_vbw,
                sweep_time_multiple=actual_multiple,
                sweep_time_s=actual_sweep_s,
            )
            self._if_agc_gain_db = 6.0 if settings.if_agc_enabled else 0.0
            self._configuration_generation += 1
            self._max_hold = IntervalMaxHoldBuffer()
            self._spectrum_temporal.reset(generation=self._configuration_generation)
            self._spectrum_temporal = NativeSpectrumTemporalAccumulator(self._point_count)
            self._spectrum_temporal_exchange.clear()
            self._waterfall.reconfigure(self._point_count, self._configuration_generation, self._waterfall_config)
            return replace(self._settings)

    def apply_amplitude_offset(self, amplitude_offset_db: float) -> float:
        value = validate_amplitude_offset(amplitude_offset_db)
        with self._lock:
            self._settings = replace(self._settings, amplitude_offset_db=value)
            self._requested_settings = replace(self._requested_settings, amplitude_offset_db=value)
            self._spectrum_temporal.reset(generation=self._configuration_generation)
            self._spectrum_temporal_exchange.clear()
        return value

    def configure_waterfall(self, config: WaterfallRateConfig) -> None:
        """Configure simulator row timing; this does not touch SAN-90 hardware."""
        with self._lock:
            self._waterfall_config = config
            self._frame_rate_hz = max(self._minimum_frame_rate_hz, config.rows_per_second * 4.0)
            self._waterfall.reconfigure(self._point_count, self._configuration_generation, config)

    def read_waterfall_batch(self) -> WaterfallBatch | None:
        return self._waterfall.exchange.take_latest()

    def get_waterfall_metrics(self) -> WaterfallProducerMetrics:
        return self._waterfall.metrics()

    def get_spectrum_publish_fps(self) -> float:
        state = self.get_settings_state()
        if state.actual.resolution_tradeoff_index is None:
            return 60.0
        return SAN90_RESOLUTION_TRADEOFF_STEPS[state.actual.resolution_tradeoff_index].spectrum_publish_fps

    def get_settings_state(self) -> AnalyzerSettingsState:
        with self._lock:
            settings = replace(self._settings)
            requested = replace(self._requested_settings)
            generation = self._configuration_generation
            if_agc_gain_db = self._if_agc_gain_db
        span = float(settings.span_hz or 0.0)
        matched = match_actual_tradeoff_step(
            SAN90_RESOLUTION_TRADEOFF_STEPS,
            actual_rbw_hz=float(settings.rbw_hz or 0.0),
            point_count=self._point_count,
            fft_size=None,
        )
        return AnalyzerSettingsState(
            requested=requested,
            actual=AnalyzerActualSettings(
                center_frequency_hz=settings.center_frequency_hz,
                start_frequency_hz=settings.center_frequency_hz - span / 2,
                stop_frequency_hz=settings.center_frequency_hz + span / 2,
                span_hz=span,
                reference_level_dbm=settings.reference_level_dbm,
                attenuation_db=settings.attenuation_db,
                attenuation_automatic=settings.attenuation_db is None,
                preamplifier=settings.preamplifier,
                gain_strategy=settings.gain_strategy,
                if_agc_enabled=settings.if_agc_enabled,
                if_agc_target_dbfs=settings.if_agc_target_dbfs,
                if_agc_period_s=settings.if_agc_period_s,
                if_agc_gain_db=if_agc_gain_db,
                rbw_hz=float(settings.rbw_hz or 0.0),
                rbw_mode=settings.rbw_mode,
                vbw_hz=settings.vbw_hz,
                vbw_mode=settings.vbw_mode,
                sweep_time_mode=settings.sweep_time_mode,
                sweep_time_multiple=settings.sweep_time_multiple,
                sweep_time_s=settings.sweep_time_s,
                window=settings.window,
                detector=settings.detector,
                fft_size=matched.fft_size if matched is not None else self._point_count,
                scale_to_dbm=None,
                offset_to_dbm=None,
                point_count=self._point_count,
                resolution_tradeoff_index=matched.index if matched is not None and settings.rbw_mode == "manual" else None,
                resolution_tradeoff_state="auto" if settings.rbw_mode == "auto" else "matched" if matched is not None else "custom",
                resolution_tradeoff_step_id=matched.id if matched is not None and settings.rbw_mode == "manual" else None,
                frequency_bin_spacing_hz=span / self._point_count,
                amplitude_offset_db=settings.amplitude_offset_db,
            ),
            configuration_generation=generation,
        )

    def read_frame(self) -> SpectrumFrame | None:
        frame = self._latest.read()
        if frame is not None:
            with self._lock:
                self._published += 1
        return frame

    def read_interval_max_hold(self) -> SpectrumFrame | None:
        return self._max_hold.take()

    def read_spectrum_temporal(self) -> SpectrumTemporalFrame | None:
        return self._spectrum_temporal_exchange.take()

    def get_spectrum_temporal_metrics(self) -> dict[str, float | int]:
        accumulator=self._spectrum_temporal;completed=accumulator.completed_intervals
        return {
            "completed_intervals":completed,"total_traces_integrated":accumulator.total_traces_integrated,
            "frames_published_to_exchange":self._spectrum_temporal_exchange.frames_published,
            "frames_displaced":self._spectrum_temporal_exchange.frames_displaced,
            "compatible_maximum_merges":self._spectrum_temporal_exchange.compatible_maximum_merges,
            "incompatible_merge_rejections":self._spectrum_temporal_exchange.incompatible_merge_rejections,
            "traces_preserved_by_merges":self._spectrum_temporal_exchange.traces_preserved_by_merges,
            "minimum_traces_integrated":accumulator.minimum_traces_integrated,"maximum_traces_integrated":accumulator.maximum_traces_integrated,
            "mean_traces_integrated":accumulator.total_traces_integrated/completed if completed else 0.0,
            "max_hold_update_total_ns":accumulator.max_hold_update_total_ns,
            "mean_max_hold_update_ns_per_interval":accumulator.max_hold_update_total_ns/completed if completed else 0.0,
            "conversion_total_ns":accumulator.conversion_total_ns,
            "mean_conversion_ns":accumulator.conversion_total_ns/completed if completed else 0.0,
            "maximum_conversion_ns":accumulator.conversion_max_ns,
            "finalization_total_ns":accumulator.finalization_total_ns,
            "mean_finalization_ns":accumulator.finalization_total_ns/completed if completed else 0.0,
            "maximum_finalization_ns":accumulator.finalization_max_ns,
            "mean_receipt_span_ns":accumulator.receipt_span_total_ns/completed if completed else 0.0,
            "minimum_receipt_span_ns":accumulator.receipt_span_min_ns,
            "maximum_receipt_span_ns":accumulator.receipt_span_max_ns,
            "missed_interval_deadlines":accumulator.missed_interval_deadlines,
            "frames_replaced":self._spectrum_temporal_exchange.frames_replaced,
            "discarded_incomplete_intervals":accumulator.discarded_incomplete_intervals,
        }

    def get_status(self) -> RuntimeStatus:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            elapsed = 0.0 if self._started_ns is None else (time.monotonic_ns() - self._started_ns) / 1e9
            return RuntimeStatus(
                source="simulator",
                connected=self._connected,
                acquisition_running=running,
                if_overflow=self._simulate_if_overflow,
                amplitude_offset_db=self._settings.amplitude_offset_db,
                sdk_frames_received=self._received,
                display_frames_published=self._published,
                frames_replaced=self._latest.replaced,
                last_frame_timestamp_ns=self._last_frame_ns,
                sdk_frames_per_second=self._received / elapsed if elapsed > 0 else 0.0,
                point_count=self._point_count,
                configuration_generation=self._configuration_generation,
            )

    def set_if_overflow(self, active: bool) -> None:
        """Minimal diagnostic hook for verifying overflow telemetry without hardware."""
        with self._lock:
            self._simulate_if_overflow = bool(active)

    def set_if_agc_gain(self, gain_db: float | None) -> None:
        """Simulator hook for focused runtime readback tests."""
        if gain_db is not None and not math.isfinite(gain_db):
            raise ValueError("IF AGC gain must be finite or None")
        with self._lock:
            self._if_agc_gain_db = gain_db

    def get_device_info(self) -> DeviceInfo | None:
        if not self._connected:
            return None
        return DeviceInfo(source="simulator", model="Spectrum simulator", serial="SIM-0001")

    def _run(self) -> None:
        deadline = time.monotonic()
        while not self._stop_event.is_set():
            try:
                frame = self._generate_frame()
                raw = np.ascontiguousarray(np.clip((frame.values + 120.0) * (255.0 / 120.0), 0, 255), dtype=np.uint8)
                receipt_ns = time.monotonic_ns()
                recorder_packet = None
                recorder_raw = None
                recording_sink = None
                ai_packet = None
                ai_metadata = None
                ai_trace_period_ns = 0
                with self._lock:
                    if frame.configuration_generation != self._configuration_generation or frame.point_count != self._point_count:
                        continue
                    self._latest.publish(frame)
                    self._max_hold.accumulate(frame)
                    span = frame.span_hz
                    metadata = RawTraceMetadata(
                            sequence=frame.sequence,
                            device_timestamp_ns=frame.timestamp_ns,
                            host_timestamp_ns=time.time_ns(),
                            receipt_monotonic_ns=receipt_ns,
                            start_frequency_hz=frame.start_frequency_hz,
                            center_frequency_hz=frame.center_frequency_hz,
                            stop_frequency_hz=frame.stop_frequency_hz,
                            span_hz=span,
                            rbw_hz=frame.rbw_hz,
                            reference_level_dbm=frame.reference_level_dbm,
                            mapping=RawAmplitudeMapping(120.0 / 255.0, -120.0),
                            configuration_generation=frame.configuration_generation,
                        )
                    temporal = self._spectrum_temporal.add_packet(
                        raw.reshape(1, raw.size),
                        metadata,
                    )
                    if temporal is not None:
                        self._spectrum_temporal_exchange.publish(temporal)
                    self._waterfall.add_trace(
                        raw,
                        frame,
                        receipt_monotonic_ns=receipt_ns,
                        host_timestamp_ns=time.time_ns(),
                    )
                    self._received += 1
                    self._last_frame_ns = frame.timestamp_ns
                    period = max(1.0 / self._frame_rate_hz, float(self._settings.sweep_time_s or 0.0))
                    # Model one native-rate packet for the optional AI branch
                    # without changing simulator display/waterfall production.
                    ai_trace_count = max(1, round(6_400 * period))
                    ai_packet = np.repeat(raw.reshape(1, raw.size), ai_trace_count, axis=0)
                    ai_metadata = replace(
                        metadata,
                        sequence=frame.sequence * ai_trace_count + ai_trace_count - 1,
                    )
                    ai_trace_period_ns = max(1, round(period * 1e9 / ai_trace_count))
                    recording_sink = self._recording_sink
                    if recording_sink is not None:
                        # The display frame already includes software Amplitude
                        # Offset. Recreate native simulator codes so the file
                        # stores native offset and software correction separately.
                        native_values = frame.values - np.float32(self._settings.amplitude_offset_db)
                        recorder_raw = np.ascontiguousarray(
                            np.clip((native_values + 120.0) * (255.0 / 120.0), 0, 255),
                            dtype=np.uint8,
                        )
                        recorder_packet = RecordingPacket(
                            configuration=RecordingConfiguration(
                                configuration_generation=frame.configuration_generation,
                                center_frequency_hz=frame.center_frequency_hz,
                                start_frequency_hz=frame.start_frequency_hz,
                                stop_frequency_hz=frame.stop_frequency_hz,
                                span_hz=frame.span_hz,
                                rbw_hz=frame.rbw_hz,
                                vbw_hz=frame.vbw_hz,
                                sweep_time_s=frame.sweep_time_s,
                                reference_level_dbm=frame.reference_level_dbm,
                                hardware_scale_db_per_code=120.0 / 255.0,
                                hardware_offset_dbm=-120.0,
                                software_amplitude_offset_db=self._settings.amplitude_offset_db,
                                frame_width=frame.point_count,
                                fft_size=frame.point_count,
                                metadata={
                                    "schema": "san90-config/1",
                                    "verified": {
                                        "window": self._settings.window,
                                        "detector": self._settings.detector,
                                        "preamplifier": self._settings.preamplifier,
                                        "gain_strategy": self._settings.gain_strategy,
                                        "if_agc_enabled": self._settings.if_agc_enabled,
                                        "rbw_mode": self._settings.rbw_mode,
                                        "vbw_mode": self._settings.vbw_mode,
                                    },
                                },
                            ),
                            first_sequence=frame.sequence,
                            trace_count=1,
                            device_packet_timestamp_ns=frame.timestamp_ns,
                            host_receipt_unix_ns=time.time_ns(),
                            host_receipt_monotonic_ns=receipt_ns,
                            nominal_trace_period_ns=int(period * 1e9),
                            packet_acquisition_duration_ns=int(period * 1e9),
                        )
                if recording_sink is not None and recorder_packet is not None and recorder_raw is not None:
                    try:
                        recording_sink.offer_packet(recorder_raw, recorder_packet)
                    except Exception:
                        # Recording is optional and must never take down the
                        # simulator/realtime pipeline.
                        pass
                if ai_packet is not None and ai_metadata is not None:
                    self._ai_stream.offer_packet(
                        ai_packet,
                        ai_metadata,
                        trace_timestamp_step_ns=ai_trace_period_ns,
                    )
            except Exception:
                self._stop_event.set()
                raise
            deadline += period
            self._stop_event.wait(max(0.0, deadline - time.monotonic()))

    def _generate_frame(self) -> SpectrumFrame:
        with self._lock:
            settings = replace(self._settings)
            sequence = self._sequence
            phase = self._phase
            generation = self._configuration_generation
            point_count = self._point_count
            self._sequence += 1
            self._phase += 1.0
        x = np.linspace(0.0, 1.0, point_count, dtype=np.float32)
        values = self._rng.uniform(-101.0, -93.0, point_count).astype(np.float32)
        values += np.sin(x * 90.0 + phase * 0.13, dtype=np.float32) * np.float32(1.1)

        def narrow(center: float, peak: float, width: float) -> np.ndarray:
            return peak - ((x - center) / width) ** 2

        values = np.maximum(values, narrow(0.285, -48.0 + 1.8 * math.sin(phase * 0.13), 0.018))
        values = np.maximum(values, -52.0 - 16.0 * ((x - 0.52) / 0.075) ** 4)
        values = np.maximum(values, narrow(0.742, -43.0 + 2.0 * math.sin(phase * 0.08), 0.0105))
        values = np.maximum(values, narrow(0.135, -59.0, 0.0091))
        # Deliberately shorter than a 60 Hz display interval. It commonly
        # disappears from the newest trace but must survive in interval max.
        if int(phase) % 23 == 7:
            hops = (0.12, 0.24, 0.38, 0.67, 0.82)
            hop = hops[(int(phase) // 23) % len(hops)]
            hop_signal = -105.0 + 62.0 * np.exp(-0.5 * ((x - hop) / 0.0035) ** 2)
            values = np.maximum(values, hop_signal)
        values = np.ascontiguousarray(values + np.float32(settings.amplitude_offset_db), dtype=np.float32)

        span = float(settings.span_hz or 0.0)
        timestamp_ns = time.time_ns()
        return SpectrumFrame(
            sequence=sequence,
            timestamp_ns=timestamp_ns,
            values=values,
            point_count=point_count,
            start_frequency_hz=settings.center_frequency_hz - span / 2,
            center_frequency_hz=settings.center_frequency_hz,
            stop_frequency_hz=settings.center_frequency_hz + span / 2,
            span_hz=span,
            rbw_hz=float(settings.rbw_hz or 0.0),
            vbw_hz=settings.vbw_hz,
            reference_level_dbm=settings.reference_level_dbm,
            sweep_time_s=settings.sweep_time_s,
            frame_type=FrameType.CURRENT,
            configuration_generation=generation,
        )
