"""One-worker, monotonic, permanently-1× SAN-90 playback engine."""

from __future__ import annotations

import bisect
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from backend.recording.format import RecordingFormatError, crc32c
from backend.recording.models import GapReason

from .index import build_playback_index
from .models import IndexedTraceBatch, MutablePlaybackStatus, PlaybackIndex, PlaybackState, PlaybackStatus
from .source import PlaybackSource


class PlaybackError(RuntimeError):
    pass


class PlaybackEngine:
    """The scheduler has no public or internal variable-speed setting."""

    def __init__(
        self,
        source: PlaybackSource | None = None,
        *,
        epoch_callback: Callable[[int, str], None] | None = None,
    ) -> None:
        self.source = source or PlaybackSource()
        self._condition = threading.Condition(threading.RLock())
        self._io_lock = threading.Lock()
        self._status = MutablePlaybackStatus()
        self._index: PlaybackIndex | None = None
        self._path: Path | None = None
        self._fd: int | None = None
        self._worker: threading.Thread | None = None
        self._stop = False
        self._next_batch = 0
        self._next_trace = 0
        self._next_gap = 0
        self._anchor_ns = 0
        self._epoch_counter = 0
        self._epoch_callback = epoch_callback

    def set_epoch_callback(self, callback: Callable[[int, str], None] | None) -> None:
        with self._condition:
            self._epoch_callback = callback

    def status(self) -> PlaybackStatus:
        with self._condition:
            return self._status.snapshot()

    @property
    def active(self) -> bool:
        return self.status().state != PlaybackState.IDLE

    def open(
        self,
        path: str | Path,
        *,
        recording_id: str,
        filename: str,
        previous_source: str,
    ) -> PlaybackStatus:
        with self._condition:
            if self._status.state != PlaybackState.IDLE:
                raise PlaybackError("a playback session is already open")
            self._epoch_counter += 1
            epoch = self._epoch_counter
            self._status = MutablePlaybackStatus(
                state=PlaybackState.OPENING,
                recording_id=recording_id,
                filename=filename,
                previous_source=previous_source,
                playback_epoch=epoch,
            )
        try:
            index = build_playback_index(path)
            if not index.batches:
                raise PlaybackError("recording contains no trace batches")
            first = index.batches[0]
            config = index.configurations[first.config_id]
            self.source.connect()
            self.source.start()
            self.source.reset_timeline(epoch, config)
            descriptor = os.open(path, os.O_RDONLY)
            with self._condition:
                self._index = index
                self._path = Path(path)
                self._fd = descriptor
                self._next_batch = 0
                self._next_trace = 0
                self._next_gap = 0
                self._stop = False
                self._status.duration_s = index.duration_s
                self._status.current_config_id = first.config_id
                self._status.configuration_generation = first.configuration_generation
                self._status.center_frequency_hz = config.center_frequency_hz
                self._status.point_count = config.frame_width
                self._status.state = PlaybackState.READY
                result = self._status.snapshot()
            self._notify_epoch(epoch, "open")
            return result
        except Exception as error:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self.source.disconnect()
            with self._condition:
                self._epoch_counter += 1
                self._status.playback_epoch = self._epoch_counter
                self._status.state = PlaybackState.FAILED
                self._status.last_error = str(error)
            self._notify_epoch(self._epoch_counter, "failure")
            raise

    def configure(self, *, auto_loop: bool, run_ai: bool) -> PlaybackStatus:
        with self._condition:
            if self._status.state == PlaybackState.IDLE:
                raise PlaybackError("no playback file is open")
            self._status.auto_loop = bool(auto_loop)
            previous_ai = self._status.run_ai
        if run_ai != previous_ai:
            try:
                self.source.set_run_ai(bool(run_ai))
            except Exception as error:
                with self._condition:
                    self._status.run_ai = False
                    self._status.ai_warning = f"Playback AI unavailable: {error}"
                    return self._status.snapshot()
        with self._condition:
            self._status.run_ai = bool(run_ai)
            self._status.ai_warning = None
            return self._status.snapshot()

    def play(self) -> PlaybackStatus:
        with self._condition:
            if self._status.state == PlaybackState.PLAYING:
                return self._status.snapshot()
            if self._status.state not in {PlaybackState.READY, PlaybackState.PAUSED}:
                raise PlaybackError(f"cannot play from {self._status.state.value}")
            self._anchor_ns = time.monotonic_ns() - int(self._status.position_s * 1e9)
            self._status.state = PlaybackState.PLAYING
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="san90-playback", daemon=True)
                self._worker.start()
            else:
                self._condition.notify_all()
            return self._status.snapshot()

    def pause(self) -> PlaybackStatus:
        with self._condition:
            if self._status.state == PlaybackState.PAUSED:
                return self._status.snapshot()
            if self._status.state != PlaybackState.PLAYING:
                raise PlaybackError(f"cannot pause from {self._status.state.value}")
            self._status.position_s = max(
                self._status.position_s,
                min(self._status.duration_s, (time.monotonic_ns() - self._anchor_ns) / 1e9),
            )
            self._status.state = PlaybackState.PAUSED
            self._condition.notify_all()
            return self._status.snapshot()

    def seek(self, position_s: float) -> PlaybackStatus:
        index = self._require_index()
        if not isinstance(position_s, (int, float)) or not 0 <= float(position_s) <= index.duration_s:
            raise PlaybackError(f"position_s must be between 0 and {index.duration_s}")
        with self._condition:
            if self._status.state not in {
                PlaybackState.READY,
                PlaybackState.PLAYING,
                PlaybackState.PAUSED,
                PlaybackState.COMPLETED,
            }:
                raise PlaybackError(f"cannot seek from {self._status.state.value}")
            self._status.state = PlaybackState.SEEKING
            self._epoch_counter += 1
            epoch = self._epoch_counter
            self._status.playback_epoch = epoch
            self._condition.notify_all()
        batch_index, trace_index = self._locate(float(position_s))
        try:
            with self._io_lock:
                batch = index.batches[batch_index]
                config = index.configurations[batch.config_id]
                self.source.reset_timeline(epoch, config)
                self._emit_single(batch_index, trace_index)
            with self._condition:
                self._set_cursor_after(batch_index, trace_index)
                self._set_current(batch_index, trace_index, position=float(position_s))
                self._recount_gaps(batch.record_index)
                self._status.state = PlaybackState.PAUSED
                result = self._status.snapshot()
            self._notify_epoch(epoch, "seek")
            return result
        except Exception as error:
            self._fail(error)
            raise

    def step(self, direction: str) -> PlaybackStatus:
        if direction not in {"previous", "next"}:
            raise PlaybackError("step direction must be 'previous' or 'next'")
        index = self._require_index()
        with self._condition:
            if self._status.state not in {PlaybackState.READY, PlaybackState.PAUSED, PlaybackState.COMPLETED}:
                raise PlaybackError(f"cannot step from {self._status.state.value}")
            if self._status.current_record_index is None:
                target_batch, target_trace = 0, 0
            else:
                current_batch, current_trace = self._current_cursor()
                target_batch, target_trace = self._adjacent(
                    current_batch, current_trace, -1 if direction == "previous" else 1
                )
            self._status.state = PlaybackState.SEEKING
            self._epoch_counter += 1
            epoch = self._epoch_counter
            self._status.playback_epoch = epoch
        try:
            with self._io_lock:
                batch = index.batches[target_batch]
                config = index.configurations[batch.config_id]
                self.source.reset_timeline(epoch, config)
                self._emit_single(target_batch, target_trace)
            with self._condition:
                self._set_cursor_after(target_batch, target_trace)
                self._set_current(
                    target_batch, target_trace,
                    position=self._trace_time(index.batches[target_batch], target_trace),
                )
                self._recount_gaps(batch.record_index)
                self._status.state = PlaybackState.PAUSED
                result = self._status.snapshot()
            self._notify_epoch(epoch, "step")
            return result
        except Exception as error:
            self._fail(error)
            raise

    def stop(self, *, timeout: float = 2.0) -> PlaybackStatus:
        with self._condition:
            if self._status.state == PlaybackState.IDLE:
                return self._status.snapshot()
            self._status.state = PlaybackState.STOPPING
            self._stop = True
            self._epoch_counter += 1
            epoch = self._epoch_counter
            self._status.playback_epoch = epoch
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)
            if worker.is_alive():
                raise PlaybackError("playback worker did not stop within timeout")
        self.source.set_run_ai(False)
        self.source.disconnect()
        descriptor, self._fd = self._fd, None
        if descriptor is not None:
            os.close(descriptor)
        with self._condition:
            self._worker = None
            self._index = None
            self._path = None
            self._next_batch = self._next_trace = self._next_gap = 0
            self._status = MutablePlaybackStatus(playback_epoch=epoch)
            result = self._status.snapshot()
        self._notify_epoch(epoch, "stop")
        return result

    def _run(self) -> None:
        try:
            index = self._require_index()
            while True:
                with self._condition:
                    while self._status.state in {PlaybackState.PAUSED, PlaybackState.SEEKING} and not self._stop:
                        self._condition.wait()
                    if self._stop:
                        return
                    if self._next_batch >= len(index.batches):
                        remaining = self._anchor_ns + int(self._status.duration_s * 1e9) - time.monotonic_ns()
                        if remaining > 0:
                            self._condition.wait(timeout=min(remaining / 1e9, 0.05))
                            continue
                        if self._status.auto_loop:
                            self._restart_loop()
                            continue
                        self.source.flush()
                        self._status.position_s = self._status.duration_s
                        self._status.state = PlaybackState.COMPLETED
                        return
                    batch_index = self._next_batch
                    trace_start = self._next_trace
                    batch = index.batches[batch_index]
                    target_ns = self._anchor_ns + int(batch.cumulative_time_s * 1e9)
                    remaining = target_ns - time.monotonic_ns()
                    if remaining > 0:
                        self._condition.wait(timeout=min(remaining / 1e9, 0.05))
                        continue
                    if -remaining > 50_000_000:
                        self._anchor_ns += -remaining - 50_000_000
                    epoch = self._status.playback_epoch

                with self._io_lock:
                    with self._condition:
                        if self._stop or self._status.state != PlaybackState.PLAYING or epoch != self._status.playback_epoch:
                            continue
                        previous_config_id = self._status.current_config_id
                    config = index.configurations[batch.config_id]
                    self.source.activate_config(config)
                    if previous_config_id != batch.config_id:
                        self._notify_epoch(epoch, "config")
                    full_payload = self._read_batch(batch)
                    payload = full_payload[trace_start * batch.frame_width :]
                    subset = replace(
                        batch,
                        first_sequence=batch.first_sequence + trace_start,
                        trace_count=batch.trace_count - trace_start,
                        payload_length=len(payload),
                    )
                    self.source.consume_batch(subset, payload, feed_ai=True)

                with self._condition:
                    if epoch != self._status.playback_epoch or self._status.state != PlaybackState.PLAYING:
                        continue
                    self._advance_gaps(batch.record_index)
                    self._next_batch = batch_index + 1
                    self._next_trace = 0
                    self._set_current(
                        batch_index, batch.trace_count - 1,
                        position=batch.cumulative_time_s,
                    )
        except Exception as error:
            if not self._stop:
                self._fail(error)

    def _restart_loop(self) -> None:
        index = self._require_index()
        self._epoch_counter += 1
        epoch = self._epoch_counter
        self._status.playback_epoch = epoch
        self._status.loop_count += 1
        self._status.position_s = 0.0
        self._status.current_sequence = None
        self._status.current_record_index = None
        self._status.current_trace_index = None
        self._status.gaps_passed = 0
        self._status.reconfiguration_pauses_passed = 0
        self._status.lost_traces_passed = 0
        self._next_batch = self._next_trace = self._next_gap = 0
        self._anchor_ns = time.monotonic_ns()
        first = index.batches[0]
        with self._io_lock:
            self.source.reset_timeline(epoch, index.configurations[first.config_id])
        self._notify_epoch(epoch, "loop")

    def _read_batch(self, batch: IndexedTraceBatch) -> bytes:
        descriptor = self._fd
        if descriptor is None:
            raise PlaybackError("playback file is unavailable")
        payload = os.pread(descriptor, batch.payload_length, batch.payload_offset)
        if len(payload) != batch.payload_length:
            raise RecordingFormatError(
                "truncated_payload", "trace payload was truncated after open", offset=batch.record_offset
            )
        if crc32c(payload) != batch.payload_crc32c:
            raise RecordingFormatError(
                "payload_crc", "trace payload CRC32C mismatch",
                offset=batch.record_offset, checksum_kind="payload",
            )
        return payload

    def _emit_single(self, batch_index: int, trace_index: int) -> None:
        index = self._require_index()
        batch = index.batches[batch_index]
        payload = self._read_batch(batch)
        start = trace_index * batch.frame_width
        raw = payload[start : start + batch.frame_width]
        single = replace(
            batch,
            first_sequence=batch.first_sequence + trace_index,
            trace_count=1,
            payload_length=batch.frame_width,
            cumulative_time_s=self._trace_time(batch, trace_index),
        )
        self.source.consume_batch(single, raw, feed_ai=False)
        self.source.flush()

    def _locate(self, position_s: float) -> tuple[int, int]:
        index = self._require_index()
        ends = [batch.cumulative_time_s for batch in index.batches]
        batch_index = min(bisect.bisect_left(ends, position_s), len(index.batches) - 1)
        batch = index.batches[batch_index]
        period_s = batch.nominal_trace_period_ns / 1e9
        if period_s <= 0:
            return batch_index, batch.trace_count - 1
        first_time = batch.cumulative_time_s - (batch.trace_count - 1) * period_s
        trace = int((position_s - first_time) // period_s)
        return batch_index, max(0, min(batch.trace_count - 1, trace))

    @staticmethod
    def _trace_time(batch: IndexedTraceBatch, trace_index: int) -> float:
        return max(
            0.0,
            batch.cumulative_time_s
            - (batch.trace_count - 1 - trace_index) * batch.nominal_trace_period_ns / 1e9,
        )

    def _current_cursor(self) -> tuple[int, int]:
        index = self._require_index()
        record_index = self._status.current_record_index
        trace_index = self._status.current_trace_index
        if record_index is None or trace_index is None:
            return 0, 0
        for batch_index, batch in enumerate(index.batches):
            if batch.record_index == record_index:
                return batch_index, trace_index
        return len(index.batches) - 1, index.batches[-1].trace_count - 1

    def _adjacent(self, batch_index: int, trace_index: int, delta: int) -> tuple[int, int]:
        index = self._require_index()
        if delta > 0:
            if trace_index + 1 < index.batches[batch_index].trace_count:
                return batch_index, trace_index + 1
            if batch_index + 1 < len(index.batches):
                return batch_index + 1, 0
            return batch_index, trace_index
        if trace_index > 0:
            return batch_index, trace_index - 1
        if batch_index > 0:
            return batch_index - 1, index.batches[batch_index - 1].trace_count - 1
        return 0, 0

    def _set_cursor_after(self, batch_index: int, trace_index: int) -> None:
        index = self._require_index()
        if trace_index + 1 < index.batches[batch_index].trace_count:
            self._next_batch, self._next_trace = batch_index, trace_index + 1
        else:
            self._next_batch, self._next_trace = batch_index + 1, 0

    def _set_current(self, batch_index: int, trace_index: int, *, position: float) -> None:
        index = self._require_index()
        batch = index.batches[batch_index]
        config = index.configurations[batch.config_id]
        self._status.position_s = min(index.duration_s, max(0.0, position))
        self._status.current_sequence = batch.first_sequence + trace_index
        self._status.current_record_index = batch.record_index
        self._status.current_trace_index = trace_index
        self._status.current_config_id = batch.config_id
        self._status.configuration_generation = batch.configuration_generation
        self._status.center_frequency_hz = config.center_frequency_hz
        self._status.point_count = batch.frame_width

    def _advance_gaps(self, record_index: int) -> None:
        index = self._require_index()
        while self._next_gap < len(index.gaps) and index.gaps[self._next_gap].record_index < record_index:
            gap = index.gaps[self._next_gap]
            self._status.gaps_passed += 1
            if gap.record.reason_code == GapReason.RECONFIGURATION_PAUSE:
                self._status.reconfiguration_pauses_passed += 1
            else:
                self._status.lost_traces_passed += gap.record.estimated_lost_trace_count
            self._next_gap += 1

    def _recount_gaps(self, record_index: int) -> None:
        self._status.gaps_passed = 0
        self._status.reconfiguration_pauses_passed = 0
        self._status.lost_traces_passed = 0
        self._next_gap = 0
        self._advance_gaps(record_index)

    def _require_index(self) -> PlaybackIndex:
        index = self._index
        if index is None:
            raise PlaybackError("no playback file is open")
        return index

    def _fail(self, error: Exception) -> None:
        with self._condition:
            self._epoch_counter += 1
            self._status.playback_epoch = self._epoch_counter
            self._status.state = PlaybackState.FAILED
            self._status.last_error = str(error)
            self._condition.notify_all()
        self._notify_epoch(self._epoch_counter, "failure")

    def _notify_epoch(self, epoch: int, reason: str) -> None:
        callback = self._epoch_callback
        if callback is not None:
            try:
                callback(epoch, reason)
            except Exception:
                pass
