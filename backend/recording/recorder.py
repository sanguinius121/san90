"""Bounded, non-blocking acquisition-facing SAN-90 recorder engine."""

from __future__ import annotations

import math
import struct
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from .format import CONFIG_HEADER_STRUCT, EVENT_HEADER_STRUCT, GAP_HEADER_STRUCT, TRACE_HEADER_STRUCT, canonical_json_bytes
from .models import (
    EventCode,
    EventSeverity,
    GapFlags,
    GapReason,
    OfferResult,
    RecorderState,
    RecorderStatus,
    RecordingConfig,
    RecordingConfiguration,
    RecordingMode,
    RecordingPacket,
    StopReason,
)
from .storage import (
    FINALIZATION_RESERVE_BYTES,
    FREE_SPACE_CHECK_BYTES,
    FREE_SPACE_CHECK_INTERVAL_S,
    RecordingStorage,
    validate_file_prefix,
    validate_recording_config_limits,
)
from .writer import San90RtaWriter


MAX_QUEUE_BYTES = 64 * 1024**2
MAX_QUEUE_ITEMS = 256
QUEUE_HIGH_WATER_RATIO = 0.70
QUEUE_CRITICAL_RATIO = 0.90
OVERRUN_DURATION_NS = 250_000_000
OVERRUN_REJECTED_BYTES = 16 * 1024**2


class RecordingConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TraceBatchItem:
    config_id: int
    packet: RecordingPacket
    payload: bytes
    estimated_file_bytes: int


@dataclass(frozen=True, slots=True)
class ConfigAndTraceBundle:
    config_id: int
    packet: RecordingPacket
    payload: bytes
    estimated_file_bytes: int


@dataclass(frozen=True, slots=True)
class GapItem:
    config_id: int
    configuration_generation: int
    expected_sequence: int
    next_sequence: int
    estimated_lost_trace_count: int
    start_monotonic_ns: int
    end_monotonic_ns: int
    start_device_timestamp_ns: int
    end_device_timestamp_ns: int
    reason_code: GapReason
    gap_flags: GapFlags
    detail_code: int = 0
    estimated_file_bytes: int = 48 + GAP_HEADER_STRUCT.size


@dataclass(frozen=True, slots=True)
class EventItem:
    event_code: EventCode
    severity: EventSeverity
    details: Mapping[str, Any]
    estimated_file_bytes: int


@dataclass(frozen=True, slots=True)
class StopItem:
    reason: StopReason


QueueItem = ConfigAndTraceBundle | TraceBatchItem | GapItem | EventItem


@dataclass(slots=True)
class _PendingGap:
    config_id: int
    generation: int
    expected_sequence: int
    first_rejected_sequence: int
    lost_traces: int
    rejected_bytes: int
    start_monotonic_ns: int
    end_monotonic_ns: int
    start_device_timestamp_ns: int
    end_device_timestamp_ns: int
    reason: GapReason
    flags: GapFlags

    def to_item(self, next_sequence: int) -> GapItem:
        return GapItem(
            self.config_id,
            self.generation,
            self.expected_sequence,
            next_sequence,
            self.lost_traces,
            self.start_monotonic_ns,
            self.end_monotonic_ns,
            self.start_device_timestamp_ns,
            self.end_device_timestamp_ns,
            self.reason,
            self.flags,
        )


_STOP_PRIORITY = {
    StopReason.START_FAILURE: 100,
    StopReason.WRITER_ERROR: 100,
    StopReason.LOW_DISK: 90,
    StopReason.FILE_SIZE_LIMIT: 80,
    StopReason.WRITER_OVERRUN: 70,
    StopReason.DEVICE_DISCONNECT: 60,
    StopReason.BACKEND_SHUTDOWN: 50,
    StopReason.FIXED_DURATION: 40,
    StopReason.USER_STOP: 30,
}


class San90RtaRecorder:
    """Owns one writer thread and a queue bounded by bytes and item count."""

    def __init__(
        self,
        *,
        max_queue_bytes: int = MAX_QUEUE_BYTES,
        max_queue_items: int = MAX_QUEUE_ITEMS,
        overrun_duration_ns: int = OVERRUN_DURATION_NS,
        overrun_rejected_bytes: int = OVERRUN_REJECTED_BYTES,
        writer_delay_s: float = 0.0,
        storage_factory: Callable[[Any], RecordingStorage] = RecordingStorage,
        writer_factory: Callable[..., San90RtaWriter] = San90RtaWriter.open_session,
    ) -> None:
        if max_queue_bytes <= 0 or max_queue_items <= 0:
            raise ValueError("queue limits must be positive")
        self.max_queue_bytes = max_queue_bytes
        self.max_queue_items = max_queue_items
        self._overrun_duration_ns = overrun_duration_ns
        self._overrun_rejected_bytes = overrun_rejected_bytes
        self._writer_delay_s = writer_delay_s
        self._storage_factory = storage_factory
        self._writer_factory = writer_factory
        self._lifecycle_lock = threading.RLock()
        # One re-entrant lifecycle lock protects both state transitions and
        # queue accounting, avoiding cross-lock ordering during stop/failure.
        self._queue_condition = threading.Condition(self._lifecycle_lock)
        self._queue: deque[QueueItem] = deque()
        self._inflight_items = 0
        self._queue_bytes = 0
        self._queued_file_bytes = 0
        self._queue_high_water_bytes = 0
        self._queue_high_water_items = 0
        self._state = RecorderState.IDLE
        self._config: RecordingConfig | None = None
        self._session_metadata: Mapping[str, Any] = {}
        self._writer: San90RtaWriter | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._done = threading.Event()
        self._stop_requested = threading.Event()
        self._accepting = False
        self._stop_reason: StopReason | None = None
        self._last_error: str | None = None
        self._started_monotonic_ns = 0
        self._stopped_monotonic_ns = 0
        self._active_fingerprint: bytes | None = None
        self._active_config_id = 0
        self._active_generation = 0
        self._next_config_id = 1
        self._expected_next_sequence: int | None = None
        self._pending_gap: _PendingGap | None = None
        self._enqueued_batches = 0
        self._written_batches = 0
        self._rejected_batches = 0
        self._rejected_traces = 0
        self._rejected_samples = 0
        self._written_bytes = 0
        self._written_traces = 0
        self._gap_count = 0
        self._lost_trace_count = 0
        self._last_write_latency_ms = 0.0
        self._part_path: str | None = None
        self._final_path: str | None = None

    def start(self, config: RecordingConfig, session_metadata: Mapping[str, Any]) -> RecorderStatus:
        self._validate_config(config)
        preview_metadata = dict(session_metadata)
        preview_metadata.setdefault("schema", "san90-session-metadata/1")
        preview_metadata["recording"] = {
            **dict(preview_metadata.get("recording", {})),
            "mode": config.mode.value,
            "requested_duration_s": config.duration_s,
            "file_size_limit_bytes": config.file_size_limit_bytes,
            "free_disk_reserve_bytes": config.free_disk_reserve_bytes,
            "started_monotonic_ns": time.monotonic_ns(),
        }
        startup_and_finalize_bytes = (
            96
            + 48 + len(canonical_json_bytes(preview_metadata))
            + 96 + len(canonical_json_bytes({"mode": config.mode.value}))
            + FINALIZATION_RESERVE_BYTES
        )
        if startup_and_finalize_bytes > config.file_size_limit_bytes:
            raise ValueError("file size limit cannot hold session metadata and finalization reserve")
        with self._lifecycle_lock:
            if self._state in {
                RecorderState.STARTING, RecorderState.RECORDING, RecorderState.STOPPING, RecorderState.FINALIZING
            }:
                raise RecordingConflictError("a recording session is already active")
            self._reset_session(config, session_metadata)
            self._state = RecorderState.STARTING
            self._thread = threading.Thread(target=self._writer_main, name="san90-rta-writer", daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self._request_stop(StopReason.START_FAILURE, "writer startup timed out")
            raise RuntimeError("recording writer did not start")
        status = self.status()
        if status.state == RecorderState.FAILED:
            raise RuntimeError(status.last_error or "recording start failed")
        return status

    def offer_packet(self, samples: np.ndarray, packet: RecordingPacket) -> OfferResult:
        """Snapshot mutable native uint8 samples exactly once after capacity reservation."""

        if self._fixed_deadline_reached():
            self._request_stop(StopReason.FIXED_DURATION)
            return OfferResult.REJECTED_STOPPING
        if self._state != RecorderState.RECORDING or not self._accepting:
            return OfferResult.REJECTED_STOPPING
        if samples.dtype != np.uint8 or samples.ndim not in {1, 2}:
            raise ValueError("recording samples must be a one- or two-dimensional uint8 array")
        frame_width = packet.configuration.frame_width
        if packet.trace_count <= 0 or frame_width < 2 or samples.size != packet.trace_count * frame_width:
            raise ValueError("sample dimensions do not match trace_count * frame_width")
        payload_size = samples.size
        fingerprint = configuration_fingerprint(packet.configuration)

        with self._queue_condition:
            if self._state != RecorderState.RECORDING or not self._accepting:
                return OfferResult.REJECTED_STOPPING
            is_new_config = fingerprint != self._active_fingerprint
            metadata_payload_size = len(canonical_json_bytes(packet.configuration.metadata)) if packet.configuration.metadata else 0
            trace_size = 48 + TRACE_HEADER_STRUCT.size + payload_size
            config_size = 48 + CONFIG_HEADER_STRUCT.size + metadata_payload_size if is_new_config else 0
            if (
                self._expected_next_sequence is not None
                and packet.first_sequence != self._expected_next_sequence
                and self._pending_gap is None
            ):
                delta = packet.first_sequence - self._expected_next_sequence
                flags = GapFlags.SEQUENCE_REGRESSED if delta < 0 else GapFlags.LOSS_COUNT_EXACT
                self._pending_gap = _PendingGap(
                    self._active_config_id,
                    self._active_generation,
                    self._expected_next_sequence,
                    self._expected_next_sequence,
                    max(0, delta),
                    0,
                    packet.host_receipt_monotonic_ns,
                    packet.host_receipt_monotonic_ns,
                    0,
                    packet.device_packet_timestamp_ns,
                    GapReason.SEQUENCE_DISCONTINUITY,
                    flags,
                )
            gap_items = 1 if self._pending_gap is not None else 0
            required_items = 1 + gap_items
            estimated_file_bytes = trace_size + config_size
            pending_gap_bytes = (48 + GAP_HEADER_STRUCT.size) if self._pending_gap is not None else 0
            # _written_bytes advances only after a complete queue item. Adding
            # queued estimates therefore counts an in-flight item exactly once.
            writer_bytes = self._written_bytes
            config = self._config
            if config is None:
                return OfferResult.REJECTED_STOPPING
            if writer_bytes + self._queued_file_bytes + estimated_file_bytes + pending_gap_bytes + FINALIZATION_RESERVE_BYTES > (
                config.file_size_limit_bytes
            ):
                self._request_stop_locked(StopReason.FILE_SIZE_LIMIT)
                return OfferResult.REJECTED_LIMIT
            if (
                self._queue_bytes + payload_size > self.max_queue_bytes
                or len(self._queue) + self._inflight_items + required_items > self.max_queue_items
            ):
                self._record_rejection_locked(packet, payload_size)
                return OfferResult.REJECTED_QUEUE_FULL

            # The source may reuse or mutate its NumPy view immediately after
            # return. This is the one required ownership copy. Immutable bytes
            # is accepted directly by google-crc32c and os.write.
            payload = samples.tobytes(order="C")
            if self._pending_gap is not None:
                gap = self._pending_gap.to_item(packet.first_sequence)
                self._queue.append(gap)
                self._queued_file_bytes += gap.estimated_file_bytes
                self._pending_gap = None
            if is_new_config:
                config_id = self._next_config_id
                self._next_config_id += 1
                item: QueueItem = ConfigAndTraceBundle(config_id, packet, payload, estimated_file_bytes)
                self._active_fingerprint = fingerprint
                self._active_config_id = config_id
                self._active_generation = packet.configuration.configuration_generation
            else:
                item = TraceBatchItem(self._active_config_id, packet, payload, estimated_file_bytes)
            self._queue.append(item)
            self._queue_bytes += payload_size
            self._queued_file_bytes += estimated_file_bytes
            self._queue_high_water_bytes = max(self._queue_high_water_bytes, self._queue_bytes)
            self._queue_high_water_items = max(
                self._queue_high_water_items, len(self._queue) + self._inflight_items
            )
            self._enqueued_batches += 1
            self._expected_next_sequence = packet.first_sequence + packet.trace_count
            self._queue_condition.notify()
        return OfferResult.ACCEPTED

    def note_reconfiguration_pause(
        self,
        *,
        start_monotonic_ns: int,
        end_monotonic_ns: int,
        next_sequence: int,
    ) -> bool:
        with self._queue_condition:
            expected = self._expected_next_sequence if self._expected_next_sequence is not None else next_sequence
            flags = GapFlags.PAUSE_WITHOUT_OBSERVED_LOSS | GapFlags.LOSS_COUNT_EXACT
            if next_sequence < expected:
                flags |= GapFlags.SEQUENCE_REGRESSED
            gap = GapItem(
                self._active_config_id,
                self._active_generation,
                expected,
                next_sequence,
                0,
                start_monotonic_ns,
                end_monotonic_ns,
                0,
                0,
                GapReason.RECONFIGURATION_PAUSE,
                flags,
            )
            if not self._accepting or len(self._queue) + self._inflight_items >= self.max_queue_items:
                return False
            self._queue.append(gap)
            self._queued_file_bytes += gap.estimated_file_bytes
            self._queue_high_water_items = max(
                self._queue_high_water_items, len(self._queue) + self._inflight_items
            )
            # The explicit pause explains the source's next sequence, including
            # generation-local sequence reset to zero on SAN-90 reconfigure.
            self._expected_next_sequence = next_sequence
            self._queue_condition.notify()
            return True

    def stop(self, reason: StopReason = StopReason.USER_STOP, *, timeout: float | None = None) -> RecorderStatus:
        self._request_stop(reason)
        if timeout is not None:
            self._done.wait(timeout)
        return self.status()

    def source_disconnected(self) -> None:
        self._request_stop(StopReason.DEVICE_DISCONNECT)

    def shutdown(self, *, timeout: float = 5.0) -> RecorderStatus:
        self._request_stop(StopReason.BACKEND_SHUTDOWN)
        self._done.wait(timeout)
        return self.status()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def status(self) -> RecorderStatus:
        with self._lifecycle_lock, self._queue_condition:
            now = self._stopped_monotonic_ns or time.monotonic_ns()
            elapsed = max(0.0, (now - self._started_monotonic_ns) / 1e9) if self._started_monotonic_ns else 0.0
            writer = self._writer
            written_bytes = writer.written_bytes if writer is not None else self._written_bytes
            trace_count = writer.trace_count if writer is not None else self._written_traces
            gap_count = writer.gap_count if writer is not None else self._gap_count
            lost_count = writer.lost_trace_count if writer is not None else self._lost_trace_count
            latency = writer.last_write_latency_ms if writer is not None else self._last_write_latency_ms
            rate = written_bytes / elapsed if elapsed > 0 else 0.0
            return RecorderStatus(
                self._state,
                str(writer.session_uuid) if writer is not None else None,
                self._part_path,
                self._final_path,
                self._config.mode if self._config else None,
                elapsed,
                written_bytes,
                trace_count,
                self._written_batches,
                gap_count,
                lost_count,
                self._queue_bytes,
                len(self._queue) + self._inflight_items,
                self._queue_bytes / self.max_queue_bytes,
                (len(self._queue) + self._inflight_items) / self.max_queue_items,
                self._queue_high_water_bytes,
                self._queue_high_water_items,
                self._enqueued_batches,
                self._written_batches,
                self._rejected_batches,
                self._rejected_traces,
                self._rejected_samples,
                rate,
                latency,
                self._stop_reason,
                self._last_error,
                self._active_config_id or None,
                self._active_generation or None,
            )

    def _writer_main(self) -> None:
        writer: San90RtaWriter | None = None
        try:
            assert self._config is not None
            storage = self._storage_factory(self._config.output_directory)
            storage.ensure_free_reserve(
                self._config.free_disk_reserve_bytes + FINALIZATION_RESERVE_BYTES
            )
            writer = self._writer_factory(storage, file_prefix=self._config.file_prefix)
            self._writer = writer
            self._part_path = str(writer.part_path)
            metadata = dict(self._session_metadata)
            metadata.setdefault("schema", "san90-session-metadata/1")
            metadata["recording"] = {
                **dict(metadata.get("recording", {})),
                "mode": self._config.mode.value,
                "requested_duration_s": self._config.duration_s,
                "file_size_limit_bytes": self._config.file_size_limit_bytes,
                "free_disk_reserve_bytes": self._config.free_disk_reserve_bytes,
                "started_monotonic_ns": self._started_monotonic_ns,
            }
            writer.write_session_metadata(metadata)
            writer.write_event(
                event_code=EventCode.RECORDING_STARTED,
                severity=EventSeverity.INFO,
                details={"mode": self._config.mode.value},
            )
            self._written_bytes = writer.written_bytes
            with self._lifecycle_lock:
                self._state = RecorderState.RECORDING
                self._accepting = True
            self._ready.set()
            last_space_check_ns = 0
            bytes_at_space_check = writer.written_bytes
            while True:
                if self._fixed_deadline_reached():
                    self._request_stop(StopReason.FIXED_DURATION)
                if self._pending_overrun_reached():
                    self._request_stop(StopReason.WRITER_OVERRUN)
                item = self._take_item(timeout=0.025)
                if item is None:
                    if self._stop_requested.is_set() and self._queue_empty():
                        break
                    continue
                item_size = item.estimated_file_bytes
                now = time.monotonic_ns()
                if (
                    now - last_space_check_ns >= int(FREE_SPACE_CHECK_INTERVAL_S * 1e9)
                    or writer.written_bytes - bytes_at_space_check >= FREE_SPACE_CHECK_BYTES
                ):
                    available = storage.free_bytes()
                    last_space_check_ns = now
                    bytes_at_space_check = writer.written_bytes
                    if (
                        available - item_size
                        <= self._config.free_disk_reserve_bytes + FINALIZATION_RESERVE_BYTES
                    ):
                        self._request_stop(StopReason.LOW_DISK)
                        self._release_item(item)
                        self._discard_queued()
                        break
                if writer.written_bytes + item_size + FINALIZATION_RESERVE_BYTES > self._config.file_size_limit_bytes:
                    self._request_stop(StopReason.FILE_SIZE_LIMIT)
                    self._release_item(item)
                    self._discard_queued()
                    break
                if self._writer_delay_s:
                    time.sleep(self._writer_delay_s)
                self._write_item(writer, item)
                self._written_bytes = writer.written_bytes
                self._release_item(item)
            with self._lifecycle_lock:
                self._state = RecorderState.FINALIZING
                self._accepting = False
            pending = self._take_pending_gap_for_finalization()
            if pending is not None:
                self._write_item(writer, pending)
            final_path = writer.finalize(stop_reason=self._stop_reason or StopReason.USER_STOP)
            self._final_path = str(final_path)
            self._written_bytes = writer.written_bytes
            self._written_traces = writer.trace_count
            self._gap_count = writer.gap_count
            self._lost_trace_count = writer.lost_trace_count
            self._last_write_latency_ms = writer.last_write_latency_ms
            with self._lifecycle_lock:
                self._stopped_monotonic_ns = time.monotonic_ns()
                self._state = RecorderState.COMPLETED
        except BaseException as error:
            failure_part_path = getattr(error, "part_path", None)
            if failure_part_path is not None:
                self._part_path = str(failure_part_path)
            if writer is not None:
                try:
                    writer.abort()
                except OSError:
                    pass
                self._written_bytes = writer.written_bytes
            self._request_stop(StopReason.WRITER_ERROR if writer is not None else StopReason.START_FAILURE, str(error))
            with self._lifecycle_lock:
                self._stopped_monotonic_ns = time.monotonic_ns()
                self._state = RecorderState.FAILED
                self._accepting = False
            self._ready.set()
        finally:
            self._done.set()
            self._ready.set()

    def _write_item(self, writer: San90RtaWriter, item: QueueItem) -> None:
        if isinstance(item, GapItem):
            writer.write_gap(
                config_id=item.config_id,
                configuration_generation=item.configuration_generation,
                expected_sequence=item.expected_sequence,
                next_sequence=item.next_sequence,
                estimated_lost_trace_count=item.estimated_lost_trace_count,
                start_monotonic_ns=item.start_monotonic_ns,
                end_monotonic_ns=item.end_monotonic_ns,
                start_device_timestamp_ns=item.start_device_timestamp_ns,
                end_device_timestamp_ns=item.end_device_timestamp_ns,
                reason_code=item.reason_code,
                gap_flags=item.gap_flags,
                detail_code=item.detail_code,
            )
            return
        if isinstance(item, EventItem):
            writer.write_event(event_code=item.event_code, severity=item.severity, details=item.details)
            return
        packet = item.packet
        if isinstance(item, ConfigAndTraceBundle):
            writer.write_config(
                config_id=item.config_id,
                configuration=packet.configuration,
                effective_first_sequence=packet.first_sequence,
                effective_host_unix_ns=packet.host_receipt_unix_ns,
                effective_host_monotonic_ns=packet.host_receipt_monotonic_ns,
            )
        writer.write_trace_batch(
            config_id=item.config_id,
            configuration_generation=packet.configuration.configuration_generation,
            first_sequence=packet.first_sequence,
            trace_count=packet.trace_count,
            frame_width=packet.configuration.frame_width,
            device_packet_timestamp_ns=packet.device_packet_timestamp_ns,
            host_receipt_unix_ns=packet.host_receipt_unix_ns,
            host_receipt_monotonic_ns=packet.host_receipt_monotonic_ns,
            nominal_trace_period_ns=packet.nominal_trace_period_ns,
            packet_acquisition_duration_ns=packet.packet_acquisition_duration_ns,
            sdk_trace_timestamp_step_raw=packet.sdk_trace_timestamp_step_raw,
            timing_flags=packet.timing_flags,
            trace_flags=packet.trace_flags,
            payload=item.payload,
        )
        self._written_batches += 1

    def _take_item(self, timeout: float) -> QueueItem | None:
        with self._queue_condition:
            if not self._queue:
                self._queue_condition.wait(timeout)
            if not self._queue:
                return None
            item = self._queue.popleft()
            self._inflight_items += 1
            return item

    def _release_item(self, item: QueueItem) -> None:
        with self._queue_condition:
            self._inflight_items -= 1
            self._queued_file_bytes -= item.estimated_file_bytes
            if isinstance(item, (TraceBatchItem, ConfigAndTraceBundle)):
                self._queue_bytes -= len(item.payload)

    def _queue_empty(self) -> bool:
        with self._queue_condition:
            return not self._queue

    def _discard_queued(self) -> None:
        with self._queue_condition:
            self._queue.clear()
            self._inflight_items = 0
            self._queue_bytes = 0
            self._queued_file_bytes = 0

    def _record_rejection_locked(self, packet: RecordingPacket, payload_size: int) -> None:
        self._rejected_batches += 1
        self._rejected_traces += packet.trace_count
        self._rejected_samples += payload_size
        now = packet.host_receipt_monotonic_ns
        if self._pending_gap is None:
            expected = self._expected_next_sequence if self._expected_next_sequence is not None else packet.first_sequence
            self._pending_gap = _PendingGap(
                self._active_config_id,
                packet.configuration.configuration_generation,
                expected,
                packet.first_sequence,
                packet.trace_count,
                payload_size,
                now,
                now,
                packet.device_packet_timestamp_ns,
                packet.device_packet_timestamp_ns,
                GapReason.QUEUE_OVERFLOW,
                GapFlags.LOSS_COUNT_EXACT,
            )
        else:
            self._pending_gap.lost_traces += packet.trace_count
            self._pending_gap.rejected_bytes += payload_size
            self._pending_gap.end_monotonic_ns = now
            self._pending_gap.end_device_timestamp_ns = packet.device_packet_timestamp_ns
        pending = self._pending_gap
        if (
            now - pending.start_monotonic_ns >= self._overrun_duration_ns
            or pending.rejected_bytes >= self._overrun_rejected_bytes
        ):
            pending.reason = GapReason.WRITER_OVERRUN
            self._request_stop_locked(StopReason.WRITER_OVERRUN)

    def _take_pending_gap_for_finalization(self) -> GapItem | None:
        with self._queue_condition:
            if self._pending_gap is None:
                return None
            pending = self._pending_gap
            next_sequence = pending.first_rejected_sequence + pending.lost_traces
            self._pending_gap = None
            return pending.to_item(next_sequence)

    def _pending_overrun_reached(self) -> bool:
        with self._queue_condition:
            pending = self._pending_gap
            if pending is None:
                return False
            reached = (
                time.monotonic_ns() - pending.start_monotonic_ns >= self._overrun_duration_ns
                or pending.rejected_bytes >= self._overrun_rejected_bytes
            )
            if reached:
                pending.reason = GapReason.WRITER_OVERRUN
            return reached

    def _request_stop(self, reason: StopReason, error: str | None = None) -> None:
        with self._queue_condition:
            self._request_stop_locked(reason, error)

    def _request_stop_locked(self, reason: StopReason, error: str | None = None) -> None:
        if self._state in {RecorderState.IDLE, RecorderState.COMPLETED, RecorderState.FAILED}:
            return
        if self._stop_reason is None or _STOP_PRIORITY[reason] > _STOP_PRIORITY[self._stop_reason]:
            self._stop_reason = reason
        if error:
            self._last_error = error
        self._accepting = False
        if self._state in {RecorderState.STARTING, RecorderState.RECORDING}:
            self._state = RecorderState.STOPPING
        self._stop_requested.set()
        self._queue_condition.notify_all()

    def _fixed_deadline_reached(self) -> bool:
        config = self._config
        return bool(
            config is not None
            and config.mode == RecordingMode.FIXED
            and config.duration_s is not None
            and self._started_monotonic_ns
            and time.monotonic_ns() - self._started_monotonic_ns >= int(config.duration_s * 1e9)
        )

    def _reset_session(self, config: RecordingConfig, metadata: Mapping[str, Any]) -> None:
        with self._queue_condition:
            self._queue.clear()
            self._inflight_items = 0
            self._queue_bytes = self._queued_file_bytes = 0
            self._queue_high_water_bytes = self._queue_high_water_items = 0
            self._config = config
            self._session_metadata = dict(metadata)
            self._writer = None
            self._ready.clear()
            self._done.clear()
            self._stop_requested.clear()
            self._accepting = False
            self._stop_reason = None
            self._last_error = None
            self._started_monotonic_ns = time.monotonic_ns()
            self._stopped_monotonic_ns = 0
            self._active_fingerprint = None
            self._active_config_id = 0
            self._active_generation = 0
            self._next_config_id = 1
            self._expected_next_sequence = None
            self._pending_gap = None
            self._enqueued_batches = self._written_batches = 0
            self._rejected_batches = self._rejected_traces = self._rejected_samples = 0
            self._written_bytes = self._written_traces = 0
            self._gap_count = self._lost_trace_count = 0
            self._last_write_latency_ms = 0.0
            self._part_path = self._final_path = None

    @staticmethod
    def _validate_config(config: RecordingConfig) -> None:
        validate_file_prefix(config.file_prefix)
        validate_recording_config_limits(config.file_size_limit_bytes, config.free_disk_reserve_bytes)
        if config.mode == RecordingMode.FIXED:
            if config.duration_s is None or not math.isfinite(config.duration_s) or config.duration_s <= 0:
                raise ValueError("fixed recording requires a finite positive duration")
        elif config.mode != RecordingMode.MANUAL:
            raise ValueError("recording mode must be fixed or manual")


def configuration_fingerprint(configuration: RecordingConfiguration) -> bytes:
    """Use version-1 on-disk precision for all decode-visible comparisons."""

    flags = (1 if configuration.vbw_hz is not None else 0) | (
        2 if configuration.sweep_time_s is not None else 0
    ) | 4
    binary = struct.pack(
        "<QB7d4fII",
        configuration.configuration_generation,
        flags,
        configuration.center_frequency_hz,
        configuration.start_frequency_hz,
        configuration.stop_frequency_hz,
        configuration.span_hz,
        configuration.rbw_hz,
        configuration.vbw_hz or 0.0,
        configuration.sweep_time_s or 0.0,
        configuration.reference_level_dbm,
        configuration.hardware_scale_db_per_code,
        configuration.hardware_offset_dbm,
        configuration.software_amplitude_offset_db,
        configuration.frame_width,
        configuration.fft_size,
    )
    relevant = {}
    for section_name in ("requested", "verified"):
        section = configuration.metadata.get(section_name)
        if isinstance(section, Mapping):
            relevant[section_name] = {
                key: section[key]
                for key in (
                    "window", "detector", "attenuation_automatic", "attenuation_db",
                    "preamplifier", "gain_strategy", "if_agc_enabled", "if_agc_target_dbfs",
                    "if_agc_period_s", "rbw_mode", "vbw_mode",
                )
                if key in section
            }
    return binary + canonical_json_bytes(relevant)
