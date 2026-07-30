"""Small synthetic SAN-90 recording fixtures; not a production writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from backend.recording.format import (
    Crc32c,
    END_RECORD_HEADER_SIZE,
    pack_configuration_record,
    pack_end_record,
    pack_event_record,
    pack_file_header,
    pack_gap_record,
    pack_record,
    pack_session_metadata,
    pack_trace_batch_record,
)
from backend.recording.models import (
    ConfigRecordFlags,
    EndFlags,
    EventCode,
    EventSeverity,
    GapFlags,
    GapReason,
    RecordType,
    StopReason,
    TimingFlags,
)


SESSION_UUID = UUID("12345678-1234-5678-1234-567812345678")
CREATED_NS = 1_800_000_000_000_000_000
START_MONOTONIC_NS = 5_000_000_000


@dataclass
class FixtureBuilder:
    records: list[bytes] = field(default_factory=list)
    trace_batch_count: int = 0
    trace_count: int = 0
    raw_sample_count: int = 0
    gap_count: int = 0
    lost_trace_count: int = 0
    config_record_count: int = 0

    def __post_init__(self) -> None:
        self.header = pack_file_header(creation_unix_ns=CREATED_NS, session_uuid=SESSION_UUID)

    @property
    def next_index(self) -> int:
        return len(self.records) + 1

    def add_session(self) -> bytes:
        record = pack_session_metadata(
            record_index=self.next_index,
            metadata={
                "schema": "san90-session-metadata/1",
                "device": {"manufacturer": "HAROGIC", "model": "SAN-90", "uid": "fixture"},
                "recording": {"mode": "fixed", "started_monotonic_ns": START_MONOTONIC_NS},
            },
        )
        self.records.append(record)
        return record

    def add_config(
        self,
        *,
        config_id: int = 1,
        generation: int = 7,
        first_sequence: int = 100,
        frame_width: int = 4,
        start_hz: float = 2_400_000_000.0,
        stop_hz: float = 2_500_000_000.0,
        amplitude_offset_db: float = 1.25,
    ) -> bytes:
        record = pack_configuration_record(
            record_index=self.next_index,
            config_id=config_id,
            configuration_generation=generation,
            effective_first_sequence=first_sequence,
            effective_host_unix_ns=CREATED_NS + 1,
            effective_host_monotonic_ns=START_MONOTONIC_NS + 1,
            center_frequency_hz=(start_hz + stop_hz) / 2,
            start_frequency_hz=start_hz,
            stop_frequency_hz=stop_hz,
            span_hz=stop_hz - start_hz,
            rbw_hz=60_306.091,
            vbw_hz=6_030.6091,
            sweep_time_s=0.00013076,
            reference_level_dbm=0.0,
            hardware_scale_db_per_code=0.5,
            hardware_offset_dbm=-100.0,
            software_amplitude_offset_db=amplitude_offset_db,
            frame_width=frame_width,
            fft_size=frame_width * 2,
            metadata={"schema": "san90-config/1", "verified": {"window": "blackman-nuttall"}},
            flags=(
                ConfigRecordFlags.VBW_VALID
                | ConfigRecordFlags.SWEEP_TIME_VALID
                | ConfigRecordFlags.OUTER_BIN_EDGES
            ),
        )
        self.records.append(record)
        self.config_record_count += 1
        return record

    def add_trace(
        self,
        *,
        config_id: int = 1,
        generation: int = 7,
        first_sequence: int = 100,
        trace_count: int = 2,
        frame_width: int = 4,
        payload: bytes | None = None,
        host_monotonic_ns: int = START_MONOTONIC_NS + 2,
        host_unix_ns: int = CREATED_NS + 2,
        nominal_trace_period_ns: int = 130_760,
    ) -> bytes:
        raw = payload if payload is not None else bytes(range(1, trace_count * frame_width + 1))
        record = pack_trace_batch_record(
            record_index=self.next_index,
            config_id=config_id,
            configuration_generation=generation,
            first_sequence=first_sequence,
            trace_count=trace_count,
            frame_width=frame_width,
            device_packet_timestamp_ns=1_700_000_000_000_000_000,
            host_receipt_unix_ns=host_unix_ns,
            host_receipt_monotonic_ns=host_monotonic_ns,
            nominal_trace_period_ns=nominal_trace_period_ns,
            packet_acquisition_duration_ns=nominal_trace_period_ns * trace_count,
            sdk_trace_timestamp_step_raw=16_384.0,
            timing_flags=TimingFlags.DEVICE_TIMESTAMP_PRESENT | TimingFlags.PERIOD_FROM_PACKET_ACQUISITION,
            payload=raw,
        )
        self.records.append(record)
        self.trace_batch_count += 1
        self.trace_count += trace_count
        self.raw_sample_count += len(raw)
        return record

    def add_gap(
        self,
        *,
        config_id: int = 1,
        generation: int = 7,
        expected_sequence: int = 102,
        next_sequence: int = 105,
        lost: int = 3,
        reason: GapReason = GapReason.SEQUENCE_DISCONTINUITY,
        flags: GapFlags = GapFlags.LOSS_COUNT_EXACT,
        start_monotonic_ns: int = START_MONOTONIC_NS + 3,
        end_monotonic_ns: int = START_MONOTONIC_NS + 4,
    ) -> bytes:
        record = pack_gap_record(
            record_index=self.next_index,
            config_id=config_id,
            configuration_generation=generation,
            expected_sequence=expected_sequence,
            next_sequence=next_sequence,
            estimated_lost_trace_count=lost,
            start_monotonic_ns=start_monotonic_ns,
            end_monotonic_ns=end_monotonic_ns,
            start_device_timestamp_ns=0,
            end_device_timestamp_ns=0,
            reason_code=reason,
            gap_flags=flags,
        )
        self.records.append(record)
        self.gap_count += 1
        self.lost_trace_count += lost
        return record

    def add_event(self) -> bytes:
        record = pack_event_record(
            record_index=self.next_index,
            event_unix_ns=CREATED_NS + 5,
            event_monotonic_ns=START_MONOTONIC_NS + 5,
            event_code=EventCode.CONFIGURATION_CHANGED,
            severity=EventSeverity.INFO,
            config_id=1,
            configuration_generation=7,
            sequence=100,
            details={"message": "fixture"},
        )
        self.records.append(record)
        return record

    def add_unknown(self, record_type: int = 0x7000) -> bytes:
        record = pack_record(
            record_type=record_type,
            record_index=self.next_index,
            payload=b"unknown-payload",
        )
        self.records.append(record)
        return record

    def finish(self, *, clean: bool = True, rolling_override: int | None = None, **counter_overrides: int) -> bytes:
        body = self.header + b"".join(self.records)
        rolling = Crc32c()
        rolling.update(body)
        bytes_before_end = len(body)
        final_file_bytes = bytes_before_end + END_RECORD_HEADER_SIZE
        counters = {
            "total_record_count": len(self.records) + 1,
            "trace_batch_count": self.trace_batch_count,
            "trace_count": self.trace_count,
            "raw_sample_count": self.raw_sample_count,
            "bytes_before_end": bytes_before_end,
            "final_file_bytes": final_file_bytes,
            "gap_count": self.gap_count,
            "lost_trace_count": self.lost_trace_count,
            "config_record_count": self.config_record_count,
        }
        counters.update(counter_overrides)
        end = pack_end_record(
            record_index=self.next_index,
            stop_unix_ns=CREATED_NS + 1_000_000_000,
            stop_monotonic_ns=START_MONOTONIC_NS + 1_000_000_000,
            stop_reason=StopReason.FIXED_DURATION,
            end_flags=EndFlags.CLEAN_FINALIZATION if clean else EndFlags.NONE,
            duration_ns=1_000_000_000,
            rolling_crc32c=rolling.value if rolling_override is None else rolling_override,
            **counters,
        )
        return body + end


def valid_fixture(*, gap: bool = False, multiple_configs: bool = False) -> bytes:
    builder = FixtureBuilder()
    builder.add_session()
    builder.add_config()
    builder.add_trace()
    next_sequence = 102
    if gap:
        builder.add_gap()
        next_sequence = 105
    if multiple_configs:
        builder.add_config(config_id=2, generation=8, first_sequence=next_sequence, frame_width=2)
        builder.add_trace(
            config_id=2,
            generation=8,
            first_sequence=next_sequence,
            trace_count=2,
            frame_width=2,
            payload=b"\x0a\x14\x1e\x28",
        )
    elif gap:
        builder.add_trace(first_sequence=next_sequence)
    return builder.finish()
