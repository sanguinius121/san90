"""Typed playback catalog, index, and status models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from backend.recording.models import ConfigurationRecord, EndRecord, GapReason, GapRecord, TimingFlags


class PlaybackState(str, Enum):
    IDLE = "idle"
    OPENING = "opening"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    SEEKING = "seeking"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RecordingSummary:
    id: str
    filename: str
    size_bytes: int
    created_at: str | None
    duration_s: float
    trace_count: int
    batch_count: int
    config_count: int
    gap_count: int
    lost_trace_count: int
    stop_reason: str | None
    complete: bool
    clean: bool
    playable: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IndexedTraceBatch:
    record_index: int
    record_offset: int
    payload_offset: int
    payload_length: int
    payload_crc32c: int
    config_id: int
    configuration_generation: int
    first_sequence: int
    trace_count: int
    frame_width: int
    device_packet_timestamp_ns: int
    host_receipt_unix_ns: int
    host_receipt_monotonic_ns: int
    nominal_trace_period_ns: int
    packet_acquisition_duration_ns: int
    timing_flags: TimingFlags
    trace_flags: int
    cumulative_time_s: float


@dataclass(frozen=True, slots=True)
class IndexedGap:
    record_index: int
    cumulative_time_s: float
    record: GapRecord

    @property
    def is_reconfiguration_pause(self) -> bool:
        return self.record.reason_code == GapReason.RECONFIGURATION_PAUSE


@dataclass(frozen=True, slots=True)
class PlaybackIndex:
    session_uuid: str
    creation_unix_ns: int
    session_metadata: Mapping[str, Any]
    configurations: Mapping[int, ConfigurationRecord]
    batches: tuple[IndexedTraceBatch, ...]
    gaps: tuple[IndexedGap, ...]
    end: EndRecord
    duration_s: float
    file_size: int


@dataclass(frozen=True, slots=True)
class PlaybackStatus:
    state: PlaybackState = PlaybackState.IDLE
    recording_id: str | None = None
    filename: str | None = None
    position_s: float = 0.0
    duration_s: float = 0.0
    progress: float = 0.0
    current_sequence: int | None = None
    current_record_index: int | None = None
    current_trace_index: int | None = None
    current_config_id: int | None = None
    configuration_generation: int | None = None
    center_frequency_hz: float | None = None
    point_count: int | None = None
    gaps_passed: int = 0
    reconfiguration_pauses_passed: int = 0
    lost_traces_passed: int = 0
    auto_loop: bool = False
    loop_count: int = 0
    run_ai: bool = False
    playback_epoch: int = 0
    ai_warning: str | None = None
    source: str = "playback"
    previous_source: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class MutablePlaybackStatus:
    state: PlaybackState = PlaybackState.IDLE
    recording_id: str | None = None
    filename: str | None = None
    position_s: float = 0.0
    duration_s: float = 0.0
    current_sequence: int | None = None
    current_record_index: int | None = None
    current_trace_index: int | None = None
    current_config_id: int | None = None
    configuration_generation: int | None = None
    center_frequency_hz: float | None = None
    point_count: int | None = None
    gaps_passed: int = 0
    reconfiguration_pauses_passed: int = 0
    lost_traces_passed: int = 0
    auto_loop: bool = False
    loop_count: int = 0
    run_ai: bool = False
    playback_epoch: int = 0
    ai_warning: str | None = None
    previous_source: str | None = None
    last_error: str | None = None

    def snapshot(self) -> PlaybackStatus:
        progress = 0.0 if self.duration_s <= 0 else min(1.0, self.position_s / self.duration_s)
        return PlaybackStatus(
            state=self.state,
            recording_id=self.recording_id,
            filename=self.filename,
            position_s=self.position_s,
            duration_s=self.duration_s,
            progress=progress,
            current_sequence=self.current_sequence,
            current_record_index=self.current_record_index,
            current_trace_index=self.current_trace_index,
            current_config_id=self.current_config_id,
            configuration_generation=self.configuration_generation,
            center_frequency_hz=self.center_frequency_hz,
            point_count=self.point_count,
            gaps_passed=self.gaps_passed,
            reconfiguration_pauses_passed=self.reconfiguration_pauses_passed,
            lost_traces_passed=self.lost_traces_passed,
            auto_loop=self.auto_loop,
            loop_count=self.loop_count,
            run_ai=self.run_ai,
            playback_epoch=self.playback_epoch,
            ai_warning=self.ai_warning,
            previous_source=self.previous_source,
            last_error=self.last_error,
        )
