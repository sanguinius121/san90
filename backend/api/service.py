"""Analyzer lifecycle, snapshot pump, and bounded WebSocket fan-out."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import resource
import time
from dataclasses import asdict
from dataclasses import replace
from typing import Any

import numpy as np

from backend.analyzer.base import AnalyzerSource
from backend.analyzer.factory import create_analyzer_source
from backend.analyzer.models import AnalyzerSettings, RuntimeStatus, SpectrumFrame, SpectrumTemporalFrame, WaterfallBatch
from backend.analyzer.errors import ControlError, ControlErrorCode
from backend.analyzer.raw_buffers import DisplaySnapshot, RawAmplitudeMapping, RawTraceMetadata
from backend.analyzer.san90 import San90Source
from backend.analyzer.simulator import SimulatorSource
from backend.analyzer.waterfall import (
    WaterfallRateConfig,
    waterfall_rate_for_profile,
    waterfall_rate_override_from_environment,
)
from backend.analyzer.tradeoff import (
    VISIBLE_TIME_SPAN_SECONDS,
    match_actual_tradeoff_step,
    validate_tradeoff_index,
    visible_rows,
)
from backend.ai_detection import AiDetectionSubscriber

from .protocol import MESSAGE_AI_DETECTIONS, MESSAGE_SPECTRUM, MESSAGE_SPECTRUM_TEMPORAL, MESSAGE_STATUS, MESSAGE_WATERFALL, pack_ai_detections, pack_spectrum, pack_spectrum_temporal, pack_status, pack_waterfall, pack_waterfall_batch

logger = logging.getLogger("san90.backend")


def _positive_rate(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


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


class ClientMailbox:
    """At most one unsent message per type for a single client."""

    def __init__(self) -> None:
        self._messages: dict[int, bytes] = {}
        self._event = asyncio.Event()
        self.replaced = 0

    def offer(self, message_type: int, message: bytes) -> None:
        if message_type in self._messages:
            self.replaced += 1
        self._messages[message_type] = message
        self._event.set()

    async def take(self) -> list[bytes]:
        await self._event.wait()
        messages = list(self._messages.values())
        self._messages.clear()
        self._event.clear()
        return messages


class AnalyzerService:
    def __init__(self, source_name: str | None = None) -> None:
        self.source_name = (source_name or os.getenv("ANALYZER_SOURCE", "simulator")).lower()
        self.source: AnalyzerSource | None = None
        spectrum_text = os.getenv("SAN90_SPECTRUM_FPS")
        self._spectrum_override = None if spectrum_text is None else _positive_rate("SAN90_SPECTRUM_FPS", 60.0)
        if self._spectrum_override is not None and self._spectrum_override != 60:
            raise ValueError("SAN90_SPECTRUM_FPS must be 60 for the fixed temporal display scheduler")
        self.spectrum_fps = 60.0
        webgl_text = os.getenv("SAN90_WEBGL_TARGET_FPS")
        self._webgl_override = None if webgl_text is None else _positive_rate("SAN90_WEBGL_TARGET_FPS", 60.0)
        if self._webgl_override is not None and self._webgl_override != 60:
            raise ValueError("SAN90_WEBGL_TARGET_FPS must be 60 for the fixed render scheduler")
        self.webgl_target_fps = 60.0
        self._waterfall_override = waterfall_rate_override_from_environment()
        self._waterfall_config = self._waterfall_override or WaterfallRateConfig(60.0, 60.0, 1)
        self.waterfall_fps = self._waterfall_config.rows_per_second
        self.waterfall_batch_fps = self._waterfall_config.batches_per_second
        self.waterfall_rows_per_batch = self._waterfall_config.rows_per_batch
        self.status_hz = _positive_rate("SAN90_STATUS_HZ", 2.0)
        self.clients: set[ClientMailbox] = set()
        self.running = False
        self._pump_task: asyncio.Task[None] | None = None
        self._ai_detection_subscriber = (
            AiDetectionSubscriber(os.getenv("AI_DETECTION_SUB_URL", "tcp://127.0.0.1:5558"))
            if _enabled("AI_DETECTION_SUB_ENABLED")
            else None
        )
        self._ai_detection_task: asyncio.Task[None] | None = None
        self._ai_detection_sequence = 0
        self._status_sequence = 0
        self.spectrum_snapshots = 0
        self.waterfall_snapshots = 0
        self.waterfall_batches = 0
        self.websocket_frames_sent = 0
        self.websocket_bytes_sent = 0
        self.waterfall_bytes_sent = 0
        self.spectrum_bytes_sent = 0
        self.spectrum_serializations = 0
        self.spectrum_serialization_total_ns = 0
        self.spectrum_serialization_max_ns = 0
        self.client_send_failures = 0
        self.device_reconnects = 0
        self.client_connections = 0
        self.client_reconnects = 0
        self.client_messages_replaced = 0
        self._last_publish_monotonic_ns: int | None = None
        self._last_log = time.monotonic()
        self._last_log_bytes = 0
        self._last_log_waterfall_bytes = 0
        self._last_log_spectrum = 0
        self._last_log_waterfall = 0
        self._last_log_waterfall_batches = 0
        self._last_process_cpu = time.process_time()
        self._control_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.running:
            return
        if self.source is None:
            self.source = create_analyzer_source(self.source_name)
            await asyncio.to_thread(self.source.connect)
            if isinstance(self.source, San90Source):
                settings = AnalyzerSettings(
                    mode="rta",
                    center_frequency_hz=float(os.getenv("SAN90_CENTER_HZ", "2450000000")),
                    span_hz=None,
                    rbw_hz=None,
                    reference_level_dbm=float(os.getenv("SAN90_REFERENCE_LEVEL_DBM", "0")),
                    attenuation_db=None,
                    preamplifier="off",
                )
                await asyncio.to_thread(self.source.apply_settings, settings)
        if isinstance(self.source, SimulatorSource):
            self._configure_simulator_waterfall(self.source)
        await asyncio.to_thread(self.source.start)
        self._sync_waterfall_config(self.source)
        self.running = True
        if self._pump_task is None or self._pump_task.done():
            self._pump_task = asyncio.create_task(self._pump(), name="analyzer-display-pump")
        if self._ai_detection_subscriber is not None and (
            self._ai_detection_task is None or self._ai_detection_task.done()
        ):
            self._ai_detection_task = asyncio.create_task(
                self._ai_detection_subscriber.run(self.publish_ai_detection_result),
                name="ai-detection-subscriber",
            )

    async def stop(self, *, disconnect: bool = False) -> None:
        self.running = False
        ai_task = self._ai_detection_task
        self._ai_detection_task = None
        if ai_task is not None:
            ai_task.cancel()
            try:
                await ai_task
            except asyncio.CancelledError:
                pass
        task = self._pump_task
        self._pump_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.source is not None:
            await asyncio.to_thread(self.source.stop)
            self._status_sequence += 1
            self.offer(MESSAGE_STATUS, pack_status(self.source_name, self._status_sequence, self.status_payload()))
            if disconnect:
                await asyncio.to_thread(self.source.disconnect)
                self.source = None

    async def reconnect(self) -> None:
        await self.stop(disconnect=True)
        self.device_reconnects += 1
        await self.start()

    def register(self) -> ClientMailbox:
        mailbox = ClientMailbox()
        self.client_connections += 1
        if self.client_connections > 1:
            self.client_reconnects += 1
        self.clients.add(mailbox)
        return mailbox

    def unregister(self, mailbox: ClientMailbox) -> None:
        self.clients.discard(mailbox)
        self.client_messages_replaced += mailbox.replaced

    def offer(self, message_type: int, message: bytes) -> None:
        for client in tuple(self.clients):
            client.offer(message_type, message)

    def publish_ai_detection_result(self, result: dict[str, Any]) -> None:
        self._ai_detection_sequence += 1
        self.offer(
            MESSAGE_AI_DETECTIONS,
            pack_ai_detections(self.source_name, self._ai_detection_sequence, result),
        )

    def mark_sent(self, message: bytes) -> None:
        size = len(message)
        self.websocket_frames_sent += 1
        self.websocket_bytes_sent += size
        if len(message) > 5 and message[5] == MESSAGE_WATERFALL:
            self.waterfall_bytes_sent += size
        elif len(message) > 5 and message[5] in (MESSAGE_SPECTRUM, MESSAGE_SPECTRUM_TEMPORAL):
            self.spectrum_bytes_sent += size

    def status_payload(self) -> dict[str, Any]:
        status = self.source.get_status() if self.source is not None else RuntimeStatus(source=self.source_name)
        diagnostics = self.source.get_diagnostics() if isinstance(self.source, San90Source) else None
        reconfiguration = self.source.get_reconfiguration_metrics() if isinstance(self.source, San90Source) else None
        now_ns = time.monotonic_ns()
        last_sdk_age_ms = None
        if diagnostics is not None and diagnostics.trace_frames_received and self.source is not None:
            receipt_ns = self.source.latest_receipt_monotonic_ns()
            if receipt_ns is not None:
                last_sdk_age_ms = (now_ns - receipt_ns) / 1e6
        raw_mapping = self.source.latest_raw_amplitude_mapping() if isinstance(self.source, San90Source) else None
        settings_state = self.source.get_settings_state() if self.source is not None else None
        actual_step = None
        if self.source is not None and settings_state is not None:
            capabilities = self.source.get_capabilities()
            actual_step = match_actual_tradeoff_step(
                capabilities.resolution_tradeoff_steps,
                actual_rbw_hz=settings_state.actual.rbw_hz,
                point_count=settings_state.actual.point_count,
                fft_size=settings_state.actual.fft_size,
                actual_span_hz=settings_state.actual.span_hz,
            )
        return {
            **asdict(status),
            "source": self.source_name,
            "reconnect_count": self.device_reconnects,
            "spectrum_publish_fps": self.spectrum_fps,
            "spectrum_render_fps": 60.0,
            "webgl_target_fps": self.webgl_target_fps,
            "waterfall_publish_fps": self.waterfall_fps,
            "waterfall_rows_per_second": self.waterfall_fps,
            "waterfall_batches_per_second": self.waterfall_batch_fps,
            "waterfall_rows_per_batch": self.waterfall_rows_per_batch,
            "visible_time_span_seconds": VISIBLE_TIME_SPAN_SECONDS,
            "visible_rows": visible_rows(self.waterfall_fps),
            "resolution_tradeoff_index": None if settings_state is None else settings_state.actual.resolution_tradeoff_index,
            "resolution_tradeoff_state": None if settings_state is None else settings_state.actual.resolution_tradeoff_state,
            "resolution_tradeoff_step_id": None if settings_state is None else settings_state.actual.resolution_tradeoff_step_id,
            "rbw_mode": None if settings_state is None else settings_state.actual.rbw_mode,
            "requested_rbw_hz": None if settings_state is None else settings_state.requested.rbw_hz,
            "actual_rbw_hz": None if settings_state is None else settings_state.actual.rbw_hz,
            "fft_size": None if settings_state is None else settings_state.actual.fft_size,
            "frequency_bin_spacing_hz": None if settings_state is None else settings_state.actual.frequency_bin_spacing_hz,
            "measured_profile_trace_rate_hz": None if actual_step is None else actual_step.measured_trace_rate_hz,
            "traces_per_spectrum_frame": None if actual_step is None or actual_step.measured_trace_rate_hz is None else actual_step.measured_trace_rate_hz / 60.0,
            "traces_per_waterfall_row": None if actual_step is None or actual_step.measured_trace_rate_hz is None else actual_step.measured_trace_rate_hz / self.waterfall_fps,
            "waterfall_batches_published": self.waterfall_batches,
            "spectrum_snapshots": self.spectrum_snapshots,
            "waterfall_snapshots": self.waterfall_snapshots,
            "replaced_display_snapshots": status.frames_replaced,
            "client_messages_replaced": self.client_messages_replaced + sum(client.replaced for client in self.clients),
            "websocket_frames_sent": self.websocket_frames_sent,
            "websocket_bytes_sent": self.websocket_bytes_sent,
            "waterfall_bytes_sent": self.waterfall_bytes_sent,
            "spectrum_bytes_sent": self.spectrum_bytes_sent,
            "spectrum_serializations": self.spectrum_serializations,
            "spectrum_serialization_total_ns": self.spectrum_serialization_total_ns,
            "spectrum_serialization_mean_ns": self.spectrum_serialization_total_ns / self.spectrum_serializations if self.spectrum_serializations else 0.0,
            "spectrum_serialization_max_ns": self.spectrum_serialization_max_ns,
            "client_send_failures": self.client_send_failures,
            "client_reconnects": self.client_reconnects,
            "active_clients": len(self.clients),
            "last_sdk_frame_age_ms": last_sdk_age_ms,
            "waterfall_raw_scale_db": None if raw_mapping is None else raw_mapping.scale_db_per_code,
            "waterfall_raw_offset_dbm": None if raw_mapping is None else raw_mapping.offset_dbm,
            "last_publish_age_ms": None if self._last_publish_monotonic_ns is None else (now_ns - self._last_publish_monotonic_ns) / 1e6,
            "invalid_frames": 0 if diagnostics is None else diagnostics.invalid_packets,
            "timeouts": 0 if diagnostics is None else diagnostics.timeouts,
            "reconfiguration": None if reconfiguration is None else asdict(reconfiguration) | {"mean_duration_s": reconfiguration.mean_duration_s},
            "ai_stream": self.ai_stream_status(),
            "waterfall_producer": self._waterfall_metrics_payload(),
            "spectrum_temporal": self.source.get_spectrum_temporal_metrics() if isinstance(self.source, (San90Source, SimulatorSource)) else None,
        }

    def ai_stream_status(self) -> dict[str, object]:
        if isinstance(self.source, San90Source):
            return self.source.get_ai_stream_status()
        return {
            "enabled": False,
            "supported": False,
            "reason": "The production AI stream consumes native SAN-90 RTA packets only",
        }

    async def set_ai_stream_enabled(self, enabled: bool) -> dict[str, object]:
        if not isinstance(self.source, San90Source):
            raise ControlError(
                ControlErrorCode.UNSUPPORTED_SETTING,
                "AI stream output requires the SAN-90 source",
                recoverable=True,
            )
        return await asyncio.to_thread(self.source.set_ai_stream_enabled, enabled)

    async def set_ai_power_profile(self, name: str) -> dict[str, object]:
        if not isinstance(self.source, San90Source):
            raise ControlError(
                ControlErrorCode.UNSUPPORTED_SETTING,
                "AI power profiles require the SAN-90 source",
                requested_value=name,
                recoverable=True,
            )
        try:
            return await asyncio.to_thread(self.source.set_ai_power_profile, name)
        except ValueError as error:
            raise ControlError(
                ControlErrorCode.VALUE_OUT_OF_RANGE,
                str(error),
                requested_value=name,
                recoverable=True,
            ) from error

    def latest_ai_preview_png(self) -> bytes | None:
        return self.source.latest_ai_preview_png() if isinstance(self.source, San90Source) else None

    def capabilities_payload(self) -> dict[str, Any]:
        if self.source is None:
            raise ControlError(ControlErrorCode.DEVICE_NOT_CONNECTED, "Analyzer source is not initialized", recoverable=True)
        capabilities = self.source.get_capabilities()
        payload = asdict(capabilities)
        payload["supported_controls"] = sorted(capabilities.supported_controls)
        return payload

    def settings_payload(self) -> dict[str, Any]:
        if self.source is None:
            raise ControlError(ControlErrorCode.DEVICE_NOT_CONNECTED, "Analyzer source is not initialized", recoverable=True)
        return asdict(self.source.get_settings_state())

    async def apply_control(self, **changes: object) -> dict[str, Any]:
        if self.source is None:
            raise ControlError(ControlErrorCode.DEVICE_NOT_CONNECTED, "Analyzer source is not initialized", recoverable=True)
        async with self._control_lock:
            source = self.source
            capabilities = source.get_capabilities()
            for field, value in changes.items():
                if field not in capabilities.supported_controls:
                    raise ControlError(ControlErrorCode.UNSUPPORTED_SETTING, f"{field} is not supported by {capabilities.source}", requested_value=value, recoverable=True)
            previous_state = source.get_settings_state()
            requested = previous_state.requested
            candidate = replace(requested, **changes)
            try:
                await asyncio.to_thread(source.apply_settings, candidate)
            except ControlError as error:
                if error.requested_value is None:
                    error.requested_value = changes
                if error.previous_actual_value is None:
                    error.previous_actual_value = asdict(previous_state.actual)
                raise
            except Exception as error:
                raise ControlError(ControlErrorCode.SDK_CONFIGURATION_FAILED, str(error), recoverable=True) from error
            if isinstance(source, SimulatorSource):
                self._configure_simulator_waterfall(source)
            else:
                self._sync_waterfall_config(source)
            return asdict(source.get_settings_state())

    async def apply_amplitude_offset(self, amplitude_offset_db: float) -> dict[str, Any]:
        """Apply application calibration without an SDK reconfiguration."""
        if self.source is None:
            raise ControlError(
                ControlErrorCode.DEVICE_NOT_CONNECTED,
                "Analyzer source is not initialized",
                recoverable=True,
            )
        async with self._control_lock:
            source = self.source
            capabilities = source.get_capabilities()
            if "amplitude_offset_db" not in capabilities.supported_controls:
                raise ControlError(
                    ControlErrorCode.UNSUPPORTED_SETTING,
                    f"amplitude_offset_db is not supported by {capabilities.source}",
                    requested_value=amplitude_offset_db,
                    recoverable=True,
                )
            try:
                await asyncio.to_thread(source.apply_amplitude_offset, amplitude_offset_db)
            except ControlError:
                raise
            except ValueError as error:
                raise ControlError(
                    ControlErrorCode.VALUE_OUT_OF_RANGE,
                    str(error),
                    requested_value=amplitude_offset_db,
                    recoverable=True,
                ) from error
            except Exception as error:
                raise ControlError(
                    ControlErrorCode.SDK_CONFIGURATION_FAILED,
                    str(error),
                    requested_value=amplitude_offset_db,
                    recoverable=True,
                ) from error
            return asdict(source.get_settings_state())

    async def apply_resolution_tradeoff(self, index: int) -> dict[str, Any]:
        if self.source is None:
            raise ControlError(ControlErrorCode.DEVICE_NOT_CONNECTED, "Analyzer source is not initialized", recoverable=True)
        capabilities = self.source.get_capabilities()
        if not capabilities.supports_resolution_tradeoff:
            raise ControlError(ControlErrorCode.UNSUPPORTED_SETTING, "Resolution trade-off is unsupported", requested_value=index, recoverable=True)
        try:
            requested_step = validate_tradeoff_index(capabilities.resolution_tradeoff_steps, index)
        except ValueError as error:
            raise ControlError(ControlErrorCode.VALUE_OUT_OF_RANGE, str(error), requested_value=index, recoverable=True) from error
        state_payload = await self.apply_control(rbw_mode="manual", rbw_hz=requested_step.requested_rbw_hz)
        actual = state_payload["actual"]
        matched = match_actual_tradeoff_step(
            capabilities.resolution_tradeoff_steps,
            actual_rbw_hz=float(actual["rbw_hz"]),
            point_count=int(actual["point_count"]),
            fft_size=int(actual["fft_size"]),
        )
        if matched is None:
            raise ControlError(
                ControlErrorCode.INVALID_PROFILE,
                "Hardware readback did not match a verified resolution trade-off step",
                requested_value=index,
                previous_actual_value=actual,
                recoverable=True,
            )
        return {
            "requested_index": index,
            "actual_index": matched.index,
            "requested_rbw_hz": requested_step.requested_rbw_hz,
            "actual_rbw_hz": actual["rbw_hz"],
            "point_count": actual["point_count"],
            "fft_size": actual["fft_size"],
            # A rolling runtime counter still contains part of the previous
            # generation immediately after reconfiguration. Return the stable,
            # hardware-measured rate attached to the matched operating point.
            "actual_sdk_trace_rate_hz": matched.measured_trace_rate_hz,
            "spectrum_publish_fps": self.spectrum_fps,
            "spectrum_render_fps": 60.0,
            "webgl_target_fps": self.webgl_target_fps,
            "waterfall_rows_per_second": self.waterfall_fps,
            "waterfall_batches_per_second": self.waterfall_batch_fps,
            "waterfall_rows_per_batch": self.waterfall_rows_per_batch,
            "visible_time_span_seconds": VISIBLE_TIME_SPAN_SECONDS,
            "visible_rows": visible_rows(self.waterfall_fps),
            "frequency_bin_spacing_hz": matched.frequency_bin_spacing_hz,
            "actual_start_frequency_hz": actual["start_frequency_hz"],
            "actual_stop_frequency_hz": actual["stop_frequency_hz"],
            "actual_span_hz": actual["span_hz"],
            "configuration_generation": state_payload["configuration_generation"],
            "step": asdict(matched),
            "settings": state_payload,
        }

    def _configure_simulator_waterfall(self, source: SimulatorSource) -> None:
        if self._waterfall_override is not None:
            config = self._waterfall_override
        else:
            actual = source.get_settings_state().actual
            config = waterfall_rate_for_profile(actual.rbw_hz, actual.point_count)
        source.configure_waterfall(config)
        self._set_waterfall_config(config)
        self._sync_waterfall_config(source)

    def _sync_waterfall_config(self, source: AnalyzerSource) -> None:
        if isinstance(source, (SimulatorSource, San90Source)):
            metrics = source.get_waterfall_metrics()
            if metrics is not None:
                self._set_waterfall_config(WaterfallRateConfig(
                    metrics.target_rows_per_second,
                    metrics.target_batches_per_second,
                    metrics.rows_per_batch,
                ))
            self.spectrum_fps = 60.0
            state = source.get_settings_state()
            capabilities = source.get_capabilities()
            step = match_actual_tradeoff_step(
                capabilities.resolution_tradeoff_steps,
                actual_rbw_hz=state.actual.rbw_hz,
                point_count=state.actual.point_count,
                fft_size=state.actual.fft_size,
            )
            self.webgl_target_fps = 60.0

    def _set_waterfall_config(self, config: WaterfallRateConfig) -> None:
        self._waterfall_config = config
        self.waterfall_fps = config.rows_per_second
        self.waterfall_batch_fps = config.batches_per_second
        self.waterfall_rows_per_batch = config.rows_per_batch

    def _waterfall_metrics_payload(self) -> dict[str, Any] | None:
        source = self.source
        if isinstance(source, (SimulatorSource, San90Source)):
            metrics = source.get_waterfall_metrics()
            return None if metrics is None else asdict(metrics)
        return None

    async def _pump(self) -> None:
        next_status = time.monotonic()
        while self.running:
            source = self.source
            if source is None:
                return
            if isinstance(source, San90Source):
                temporal = source.read_spectrum_temporal()
                if temporal is not None:
                    serialization_started = time.perf_counter_ns()
                    message = pack_spectrum_temporal("san90", temporal)
                    serialization_ns = time.perf_counter_ns() - serialization_started
                    self.spectrum_serializations += 1
                    self.spectrum_serialization_total_ns += serialization_ns
                    self.spectrum_serialization_max_ns = max(self.spectrum_serialization_max_ns, serialization_ns)
                    self.offer(MESSAGE_SPECTRUM_TEMPORAL, message)
                    self.spectrum_snapshots += 1
                    self._last_publish_monotonic_ns = time.monotonic_ns()
                batch = source.read_waterfall_batch()
                if batch is not None:
                    self._publish_waterfall_batch("san90", batch)
            else:
                temporal = source.read_spectrum_temporal() if isinstance(source, SimulatorSource) else None
                if temporal is not None:
                    self._publish_simulator_temporal(temporal)
                batch = source.read_waterfall_batch() if isinstance(source, SimulatorSource) else None
                if batch is not None:
                    self._publish_waterfall_batch("simulator", batch)
            now = time.monotonic()
            if now >= next_status:
                self._status_sequence += 1
                self.offer(MESSAGE_STATUS, pack_status(self.source_name, self._status_sequence, self.status_payload()))
                next_status = now + 1.0 / self.status_hz
            if now - self._last_log >= 1.0:
                self._log_metrics(now)
            await asyncio.sleep(0.001)

    def _publish_snapshot(self, snapshot: DisplaySnapshot) -> None:
        if snapshot.spectrum_ready:
            self.offer(MESSAGE_SPECTRUM, pack_spectrum("san90", snapshot.metadata, snapshot.spectrum_float32))
            self.spectrum_snapshots += 1
        if snapshot.waterfall_ready:
            self.offer(MESSAGE_WATERFALL, pack_waterfall("san90", snapshot.metadata, snapshot.waterfall_uint8))
            self.waterfall_snapshots += 1
        self._last_publish_monotonic_ns = time.monotonic_ns()

    def _publish_simulator_spectrum(self, frame: SpectrumFrame) -> None:
        now_ns = time.time_ns()
        metadata = RawTraceMetadata(
            sequence=frame.sequence,
            device_timestamp_ns=frame.timestamp_ns,
            host_timestamp_ns=now_ns,
            receipt_monotonic_ns=time.monotonic_ns(),
            start_frequency_hz=frame.start_frequency_hz,
            center_frequency_hz=frame.center_frequency_hz,
            stop_frequency_hz=frame.stop_frequency_hz,
            span_hz=frame.span_hz,
            rbw_hz=frame.rbw_hz,
            reference_level_dbm=frame.reference_level_dbm,
            mapping=RawAmplitudeMapping(1.0, 0.0),
            configuration_generation=frame.configuration_generation,
        )
        self.offer(MESSAGE_SPECTRUM, pack_spectrum("simulator", metadata, frame.values))
        self.spectrum_snapshots += 1
        self._last_publish_monotonic_ns = time.monotonic_ns()

    def _publish_simulator_temporal(self, frame: SpectrumTemporalFrame) -> None:
        serialization_started = time.perf_counter_ns()
        message = pack_spectrum_temporal("simulator", frame)
        serialization_ns = time.perf_counter_ns() - serialization_started
        self.spectrum_serializations += 1
        self.spectrum_serialization_total_ns += serialization_ns
        self.spectrum_serialization_max_ns = max(self.spectrum_serialization_max_ns, serialization_ns)
        self.offer(MESSAGE_SPECTRUM_TEMPORAL, message)
        self.spectrum_snapshots += 1
        self._last_publish_monotonic_ns = time.monotonic_ns()

    def _publish_waterfall_batch(self, source: str, batch: WaterfallBatch) -> None:
        self.offer(MESSAGE_WATERFALL, pack_waterfall_batch(source, batch))
        self.waterfall_snapshots += batch.row_count
        self.waterfall_batches += 1
        self._last_publish_monotonic_ns = time.monotonic_ns()

    def _log_metrics(self, now: float) -> None:
        elapsed = now - self._last_log
        status = self.status_payload()
        bytes_per_second = (self.websocket_bytes_sent - self._last_log_bytes) / elapsed
        waterfall_bytes_per_second = (self.waterfall_bytes_sent - self._last_log_waterfall_bytes) / elapsed
        spectrum_rate = (self.spectrum_snapshots - self._last_log_spectrum) / elapsed
        waterfall_rate = (self.waterfall_snapshots - self._last_log_waterfall) / elapsed
        waterfall_batch_rate = (self.waterfall_batches - self._last_log_waterfall_batches) / elapsed
        memory_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        process_cpu_now = time.process_time()
        process_cpu_percent = 100.0 * (process_cpu_now - self._last_process_cpu) / elapsed
        diagnostics = self.source.get_diagnostics() if isinstance(self.source, San90Source) else None
        native_copy_ms = 0.0 if diagnostics is None or not diagnostics.packets_received else 1000.0 * diagnostics.native_copy_total_s / diagnostics.packets_received
        conversion_ms = 0.0 if diagnostics is None or not diagnostics.display_snapshots_created else 1000.0 * diagnostics.display_conversion_total_s / diagnostics.display_snapshots_created
        snapshot_ms = 0.0 if diagnostics is None or not diagnostics.display_snapshots_created else 1000.0 * diagnostics.snapshot_total_s / diagnostics.display_snapshots_created
        point_rate_mps = status["sdk_frames_per_second"] * (status["point_count"] or 0) / 1e6
        ai = status["ai_stream"]
        logger.info(
            "analyzer_metrics source=%s sdk_fps=%.1f point_rate_Mps=%.2f points=%s process_cpu_pct=%.1f "
            "native_copy_ms=%.4f conversion_ms=%.4f snapshot_ms=%.4f spectrum_fps=%.1f waterfall_rows_ps=%.1f waterfall_batches_ps=%.1f "
            "replaced=%s waterfall_Bps=%.0f websocket_Bps=%.0f clients=%s timeouts=%s invalid=%s errors=%s "
            "last_sdk_age_ms=%s last_publish_age_ms=%s memory_MiB=%.1f "
            "ai_enabled=%s ai_created_fps=%.1f ai_sent_fps=%.1f ai_queue=%s ai_drop_queue=%s ai_drop_buffer=%s ai_drop_send=%s",
            self.source_name,
            status["sdk_frames_per_second"],
            point_rate_mps,
            status["point_count"],
            process_cpu_percent,
            native_copy_ms,
            conversion_ms,
            snapshot_ms,
            spectrum_rate,
            waterfall_rate,
            waterfall_batch_rate,
            status["replaced_display_snapshots"],
            waterfall_bytes_per_second,
            bytes_per_second,
            len(self.clients),
            status["timeouts"],
            status["invalid_frames"],
            status["acquisition_errors"],
            None if status["last_sdk_frame_age_ms"] is None else round(status["last_sdk_frame_age_ms"], 3),
            None if status["last_publish_age_ms"] is None else round(status["last_publish_age_ms"], 3),
            memory_mib,
            ai.get("enabled", False),
            float(ai.get("ai_created_fps", 0.0)),
            float(ai.get("ai_actual_output_fps", 0.0)),
            ai.get("ai_queue_depth", 0),
            ai.get("ai_images_dropped_queue_total", 0),
            ai.get("ai_images_dropped_no_buffer_total", 0),
            ai.get("ai_images_dropped_send_total", 0),
        )
        self._last_log = now
        self._last_log_bytes = self.websocket_bytes_sent
        self._last_log_waterfall_bytes = self.waterfall_bytes_sent
        self._last_log_spectrum = self.spectrum_snapshots
        self._last_log_waterfall = self.waterfall_snapshots
        self._last_log_waterfall_batches = self.waterfall_batches
        self._last_process_cpu = process_cpu_now
