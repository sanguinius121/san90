# SAN-90 native RTA recording format and recorder design

Status: format version 1.0. The binary layer, sequential reader/inspection CLI,
production sequential writer, bounded recorder engine, and simulator recording
hook are implemented. The real SAN-90 acquisition hook, persistent backend
configuration, and REST control/status APIs are also implemented and
short-hardware validated. The frontend Record UI is implemented against the
REST API; playback remains deferred.

## 1. Scope and decisions

The application-owned recording extension is:

```text
*.san90rta
```

An active recording uses the same name with a trailing `.part`:

```text
SAN90_RTA_20260729T143012.123456Z_4f17c290.san90rta.part
```

The format is not SAStudio `.rtspectrum` and makes no compatibility claim.
Version 1 preserves native `uint8` RTA samples and small configuration/event
metadata. It does not compress samples.

The logical sequence is:

```text
FILE_HEADER
SESSION_METADATA
EVENT(recording_started)
CONFIG_RECORD(config_id=1, configuration_generation=N)
TRACE_BATCH_RECORD(config_id=1)
...
GAP_RECORD(optional)
CONFIG_RECORD(config_id=2, configuration_generation=N+1)
TRACE_BATCH_RECORD(config_id=2)
...
EVENT(stop requested)
END_RECORD
```

`config_id` is a file-local, monotonically increasing identifier. It is
distinct from the analyzer's `configuration_generation`: more than one
`config_id` may have the same generation when a decode-critical runtime value
changes without a hardware reconfiguration. Examples are `ScaleTodBm`,
`OffsetTodBm`, or software Amplitude Offset. Every trace batch references both
identifiers.

All multi-byte values are little-endian. Integers use the exact widths in the
tables below. IEEE-754 binary32 and binary64 are used for floating-point
values. Records are packed without implicit padding and have no alignment
requirement.

## 2. Checksums, limits, and compatibility

- The checksum algorithm is CRC32C (Castagnoli), represented as an unsigned
  little-endian `uint32`. The implementation should use a C-backed,
  hardware-accelerated implementation such as `google-crc32c`; a per-byte
  Python implementation is not acceptable in the writer hot path.
- The file header, every record header, and every non-empty payload are
  protected. CRC32C of an empty payload is zero.
- A record header CRC is calculated over the complete `header_length` bytes
  with only the `header_crc32c` field at offsets 28–31 set to zero. The stored
  payload CRC remains part of the protected header.
- `END_RECORD.rolling_crc32c` is an incremental CRC32C over every byte from
  file offset zero up to, but excluding, the `END_RECORD` prefix.
- Version 1 limits a record header to 65,536 bytes and a complete record to
  1 GiB. Implementations should normally keep trace payloads below 16 MiB.
- Readers reject an unsupported major version. A reader may accept a newer
  minor version when it understands the file header and common record prefix.
- An unknown record type is skipped using `total_record_length`, after its
  header and payload lengths and CRCs have been validated.
- No padding is present between records. The next record starts at
  `current_offset + total_record_length`.

CRC32C detects accidental truncation and corruption; it is not an
authentication mechanism.

## 3. File header

The version-1 file header is exactly 96 bytes. Canonical Python `struct`
format:

```python
FILE_HEADER_STRUCT = struct.Struct("<8sHHIIIQ16sIIQQ20sI")
```

| Offset | Field | Type | Size | Unit/value | Description |
|---:|---|---|---:|---|---|
| 0 | `magic` | `char[8]` | 8 | `SAN90RTA` | File identity |
| 8 | `format_major` | `uint16` | 2 | `1` | Breaking format version |
| 10 | `format_minor` | `uint16` | 2 | `0` | Backward-compatible version |
| 12 | `byte_order_marker` | `uint32` | 4 | `0x01020304` | Written little-endian |
| 16 | `header_length` | `uint32` | 4 | `96` | First-version header length |
| 20 | `file_flags` | `uint32` | 4 | bit field | Initially zero |
| 24 | `creation_unix_ns` | `uint64` | 8 | ns | Host wall-clock creation time |
| 32 | `session_uuid` | `uint8[16]` | 16 | UUID bytes | RFC-4122 UUID represented by `UUID.bytes` |
| 48 | `record_prefix_length` | `uint32` | 4 | `48` | Common prefix size |
| 52 | `max_record_header_length` | `uint32` | 4 | `65_536` | Reader allocation bound |
| 56 | `first_record_offset` | `uint64` | 8 | bytes | Normally `96` |
| 64 | `max_record_length` | `uint64` | 8 | `1_073_741_824` | Header plus payload bound |
| 72 | `reserved` | `uint8[20]` | 20 | zero | Future expansion |
| 92 | `header_crc32c` | `uint32` | 4 | CRC32C | CRC over bytes 0–95 with this field zero |

The file header is immutable. Clean completion is indicated only by a valid
`END_RECORD`; the writer does not seek back to mark the header complete.

## 4. Common record prefix

Every record begins with this 48-byte prefix:

```python
RECORD_PREFIX_STRUCT = struct.Struct("<4sHBBIQQIIIQ")
```

| Offset | Field | Type | Size | Description |
|---:|---|---|---:|---|
| 0 | `record_magic` | `char[4]` | 4 | `S9RR` |
| 4 | `record_type` | `uint16` | 2 | Type enumeration below |
| 6 | `record_version` | `uint8` | 1 | Version scoped to this record type |
| 7 | `record_flags` | `uint8` | 1 | Type-specific flags |
| 8 | `header_length` | `uint32` | 4 | Prefix plus type-specific header |
| 12 | `payload_length` | `uint64` | 8 | Bytes after the header |
| 20 | `record_index` | `uint64` | 8 | Starts at 1 and increments by one |
| 28 | `header_crc32c` | `uint32` | 4 | Header CRC rule defined above |
| 32 | `payload_crc32c` | `uint32` | 4 | Zero for empty payload |
| 36 | `reserved` | `uint32` | 4 | Must be zero |
| 40 | `total_record_length` | `uint64` | 8 | Exactly `header_length + payload_length` |

Record types:

| Value | Name | Version | Payload |
|---:|---|---:|---|
| `0x0001` | `SESSION_METADATA` | 1 | UTF-8 JSON |
| `0x0002` | `CONFIG_RECORD` | 1 | UTF-8 JSON details |
| `0x0003` | `TRACE_BATCH_RECORD` | 1 | Native contiguous `uint8` |
| `0x0004` | `GAP_RECORD` | 1 | Normally empty |
| `0x0005` | `EVENT_RECORD` | 1 | Optional UTF-8 JSON detail |
| `0x00ff` | `END_RECORD` | 1 | Empty in version 1 |

## 5. Session metadata

`SESSION_METADATA` has no type-specific binary header, so `header_length=48`.
Its JSON payload is small, length-bounded, and encoded as canonical UTF-8
without a BOM. Readers must not require unknown JSON keys to be absent.

Version 1 schema:

```json
{
  "schema": "san90-session-metadata/1",
  "device": {
    "manufacturer": "HAROGIC",
    "model": "SAN-90",
    "uid": null,
    "firmware_version": null,
    "api_version": "0.55.88",
    "fpga_version": null,
    "mcu_version": null
  },
  "application": {
    "name": "san90",
    "version": null,
    "git_commit": null
  },
  "host": {
    "hostname": "host-name",
    "platform": "linux",
    "architecture": "x86_64"
  },
  "recording": {
    "mode": "fixed",
    "requested_duration_s": 5.0,
    "file_size_limit_bytes": 4294967296,
    "free_disk_reserve_bytes": 2147483648,
    "started_monotonic_ns": 1234567890
  },
  "initial_requested_configuration": {}
}
```

Unavailable device values are JSON `null`, not guessed. The first
`CONFIG_RECORD`, rather than the initial summary, is authoritative for trace
decoding.

## 6. Configuration record

The version-1 header is 168 bytes:

```python
CONFIG_HEADER_STRUCT = struct.Struct("<QQQQQ7d4fII")
# common prefix (48) + CONFIG_HEADER_STRUCT.size (120) = 168
```

| Offset | Field | Type | Size | Unit | Source/meaning |
|---:|---|---|---:|---|---|
| 48 | `config_id` | `uint64` | 8 | — | File-local ID, starts at 1 |
| 56 | `configuration_generation` | `uint64` | 8 | — | Analyzer generation |
| 64 | `effective_first_sequence` | `uint64` | 8 | trace | First sequence decoded by this config |
| 72 | `effective_host_unix_ns` | `uint64` | 8 | ns | Host wall-clock activation |
| 80 | `effective_host_monotonic_ns` | `uint64` | 8 | ns | Monotonic activation |
| 88 | `center_frequency_hz` | `float64` | 8 | Hz | Verified actual |
| 96 | `start_frequency_hz` | `float64` | 8 | Hz | Verified actual |
| 104 | `stop_frequency_hz` | `float64` | 8 | Hz | Verified actual |
| 112 | `span_hz` | `float64` | 8 | Hz | Verified actual |
| 120 | `rbw_hz` | `float64` | 8 | Hz | Verified actual |
| 128 | `vbw_hz` | `float64` | 8 | Hz | Valid only when flag bit 0 is set |
| 136 | `sweep_time_s` | `float64` | 8 | s | Valid only when flag bit 1 is set |
| 144 | `reference_level_dbm` | `float32` | 4 | dBm | Verified actual |
| 148 | `hardware_scale_db_per_code` | `float32` | 4 | dB/code | Current `RTA_PlotInfo.ScaleTodBm` |
| 152 | `hardware_offset_dbm` | `float32` | 4 | dBm | Native `RTA_PlotInfo.OffsetTodBm` |
| 156 | `software_amplitude_offset_db` | `float32` | 4 | dB | Application correction |
| 160 | `frame_width` | `uint32` | 4 | samples | Points per trace |
| 164 | `fft_size` | `uint32` | 4 | samples | Zero only when unavailable |

Configuration record flag bits:

| Bit | Meaning |
|---:|---|
| 0 | `vbw_hz` is available |
| 1 | `sweep_time_s` is available |
| 2 | Start/stop describe outer bin edges; samples are bin centers |

Validation requires finite frequency and power fields, `stop > start`,
`span ≈ stop - start`, positive RBW, positive scale, and `frame_width >= 2`.
Version 1 writers set flag bit 2 to match the current SAN-90 application and
measured profile convention. The frequency axis is reconstructed as:

```text
frequency[i] =
    start_frequency_hz
    + (i + 0.5) * (stop_frequency_hz - start_frequency_hz) / frame_width
```

This gives the verified bin spacing `span_hz / frame_width` and matches the
frequency-to-bin mapping already used by the spectrum, spectrogram, and AI
annotation paths. A future format version may define another model, but a
reader must not infer one from point count alone.

Absolute power is reconstructed exactly once as:

```text
dBm =
    raw_uint8 * hardware_scale_db_per_code
    + hardware_offset_dbm
    + software_amplitude_offset_db
```

The current acquisition path constructs a corrected runtime mapping whose
offset already includes Amplitude Offset. Recorder integration must therefore
capture the native `RTA_PlotInfo` scale/offset separately and must not store
that corrected offset as `hardware_offset_dbm`.

The optional JSON payload retains non-bulk configuration details:

```json
{
  "schema": "san90-config/1",
  "requested": {
    "center_frequency_hz": 2450000000.0,
    "rbw_mode": "auto",
    "rbw_hz": null,
    "reference_level_dbm": 0.0,
    "attenuation_db": null,
    "preamplifier": "off",
    "gain_strategy": "low-noise",
    "if_agc_enabled": true,
    "if_agc_target_dbfs": -9.0,
    "if_agc_period_s": 0.0,
    "window": "blackman-nuttall",
    "detector": "positive-peak"
  },
  "verified": {
    "rbw_mode": "auto",
    "vbw_mode": "ratio-0.1",
    "attenuation_automatic": true,
    "attenuation_db": 10,
    "preamplifier": "off",
    "gain_strategy": "low-noise",
    "if_agc_enabled": true,
    "window": "blackman-nuttall",
    "detector": "positive-peak"
  },
  "runtime_at_activation": {
    "if_agc_gain_db": null
  }
}
```

Requested values are historical intent. Binary core fields and `verified`
JSON values are hardware readback. `runtime_at_activation` is telemetry and
must not be presented as a hardware configuration guarantee.

## 7. Trace batch record

The version-1 header is 136 bytes:

```python
TRACE_HEADER_STRUCT = struct.Struct("<QQQIIQQQQQdII")
# common prefix (48) + TRACE_HEADER_STRUCT.size (88) = 136
```

| Offset | Field | Type | Size | Unit | Description |
|---:|---|---|---:|---|---|
| 48 | `config_id` | `uint64` | 8 | — | Earlier configuration record |
| 56 | `configuration_generation` | `uint64` | 8 | — | Must match referenced config |
| 64 | `first_sequence` | `uint64` | 8 | trace | Sequence of trace zero |
| 72 | `trace_count` | `uint32` | 4 | traces | Normally SDK `PacketFrame` |
| 76 | `frame_width` | `uint32` | 4 | samples | Must match referenced config |
| 80 | `device_packet_timestamp_ns` | `uint64` | 8 | device ns | Zero when unavailable |
| 88 | `host_receipt_unix_ns` | `uint64` | 8 | ns | Host wall-clock packet receipt |
| 96 | `host_receipt_monotonic_ns` | `uint64` | 8 | ns | Host monotonic packet receipt |
| 104 | `nominal_trace_period_ns` | `uint64` | 8 | ns | Derived timing when flag says valid |
| 112 | `packet_acquisition_duration_ns` | `uint64` | 8 | ns | SDK `PacketAcqTime`, converted to ns |
| 120 | `sdk_trace_timestamp_step_raw` | `float64` | 8 | SDK timer counts | Preserved without claiming seconds |
| 128 | `timing_flags` | `uint32` | 4 | bit field | Semantics below |
| 132 | `reserved` | `uint32` | 4 | zero | Future expansion |

Trace `record_flags`:

| Bit | Meaning |
|---:|---|
| 0 | SDK returned IF-overflow for this packet |
| 1 | Application IF-overflow latch was active |

Timing flags:

| Bit | Meaning |
|---:|---|
| 0 | Device packet timestamp is present |
| 1 | Device timestamp is confirmed to use the host Unix epoch |
| 2 | Nominal trace period was derived from `PacketAcqTime / PacketFrame` |
| 3 | SDK trace timestamp step units are confirmed |

For the current SAN-90, bit 2 is set and bits 1 and 3 remain clear. The SDK
returns `TraceTimestampStep=16384` in an undocumented device-timer domain.
The application currently obtains a period consistent with measured trace
rate from `PacketAcqTime / PacketFrame`; the raw SDK value is preserved for
future interpretation.

Payload ordering is row-major and contains no per-trace header:

```text
trace 0: sample 0 ... sample frame_width-1
trace 1: sample 0 ... sample frame_width-1
...
trace trace_count-1
```

The following equality is mandatory:

```text
payload_length == trace_count * frame_width
```

The last sequence is `first_sequence + trace_count - 1`. A zero trace count,
zero width, arithmetic overflow, mismatch with the referenced config, or
payload-length mismatch invalidates the record.

## 8. Gap record

The 128-byte gap record has no payload in version 1:

```python
GAP_HEADER_STRUCT = struct.Struct("<QQQQQQQQQHHI")
# common prefix (48) + GAP_HEADER_STRUCT.size (80) = 128
```

| Offset | Field | Type | Size | Unit | Description |
|---:|---|---|---:|---|---|
| 48 | `config_id` | `uint64` | 8 | — | Zero if no config applies |
| 56 | `configuration_generation` | `uint64` | 8 | — | Generation around gap |
| 64 | `expected_sequence` | `uint64` | 8 | trace | First sequence expected |
| 72 | `next_sequence` | `uint64` | 8 | trace | First known sequence after gap |
| 80 | `estimated_lost_trace_count` | `uint64` | 8 | traces | Zero when pause has no proven loss |
| 88 | `start_monotonic_ns` | `uint64` | 8 | ns | Gap start |
| 96 | `end_monotonic_ns` | `uint64` | 8 | ns | Gap end, zero until known |
| 104 | `start_device_timestamp_ns` | `uint64` | 8 | device ns | Zero when unavailable |
| 112 | `end_device_timestamp_ns` | `uint64` | 8 | device ns | Zero when unavailable |
| 120 | `reason_code` | `uint16` | 2 | enum | Reason below |
| 122 | `gap_flags` | `uint16` | 2 | bit field | Estimated/observed semantics |
| 124 | `detail_code` | `uint32` | 4 | implementation | Usually zero |

Reason codes:

| Value | Name | Meaning |
|---:|---|---|
| 1 | `QUEUE_OVERFLOW` | Recorder could not retain a batch |
| 2 | `SEQUENCE_DISCONTINUITY` | Acquisition sequence jumped |
| 3 | `RECONFIGURATION_PAUSE` | Normal stop/configure/start interval |
| 4 | `DEVICE_DISCONNECT` | Source became unavailable |
| 5 | `WRITER_OVERRUN` | Sustained saturation forced stop |
| 6 | `UNKNOWN` | Gap detected without a stronger classification |

Gap flag bit 0 means loss count is exact; bit 1 means estimated; bit 2 means
the sequence regressed or restarted; bit 3 means the gap is a pause with no
observed lost sequence.

For a reconfiguration pause with continuous sequence numbering,
`expected_sequence == next_sequence`, loss count is zero, and flag bit 3 is
set. Queue overflow gaps are coalesced but must preserve the first expected
sequence and next retained sequence.

## 9. Event record

The event header is 96 bytes. Its optional payload is small UTF-8 JSON:

```python
EVENT_HEADER_STRUCT = struct.Struct("<QQHHIQQQ")
# common prefix (48) + EVENT_HEADER_STRUCT.size (48) = 96
```

| Offset | Field | Type | Size | Unit | Description |
|---:|---|---|---:|---|---|
| 48 | `event_unix_ns` | `uint64` | 8 | ns | Host wall clock |
| 56 | `event_monotonic_ns` | `uint64` | 8 | ns | Host monotonic |
| 64 | `event_code` | `uint16` | 2 | enum | Event |
| 66 | `severity` | `uint16` | 2 | enum | Info/warning/error |
| 68 | `reserved` | `uint32` | 4 | zero | Future expansion |
| 72 | `config_id` | `uint64` | 8 | — | Zero if not applicable |
| 80 | `configuration_generation` | `uint64` | 8 | — | Zero if not applicable |
| 88 | `sequence` | `uint64` | 8 | trace | Zero if not applicable |

Event codes:

| Value | Name |
|---:|---|
| 1 | `RECORDING_STARTED` |
| 2 | `USER_STOP_REQUESTED` |
| 3 | `FIXED_DURATION_REACHED` |
| 4 | `FILE_SIZE_LIMIT_REACHED` |
| 5 | `LOW_DISK_STOP` |
| 6 | `DEVICE_DISCONNECTED` |
| 7 | `DEVICE_RECONNECTED` |
| 8 | `IF_OVERFLOW_ENTERED` |
| 9 | `IF_OVERFLOW_CLEARED` |
| 10 | `CONFIGURATION_CHANGED` |
| 11 | `WRITER_WARNING` |
| 12 | `WRITER_ERROR` |

Severity values are `1=INFO`, `2=WARNING`, and `3=ERROR`. Events are
explanatory; required state transitions, decode metadata, and loss accounting
must not depend solely on an event payload.

## 10. End record

The version-1 end header is 160 bytes with no payload:

```python
END_HEADER_STRUCT = struct.Struct("<QQHHIQQQQQQQQQQII")
# common prefix (48) + END_HEADER_STRUCT.size (112) = 160
```

| Offset | Field | Type | Size | Unit | Description |
|---:|---|---|---:|---|---|
| 48 | `stop_unix_ns` | `uint64` | 8 | ns | Host wall-clock stop |
| 56 | `stop_monotonic_ns` | `uint64` | 8 | ns | Host monotonic stop |
| 64 | `stop_reason` | `uint16` | 2 | enum | Reason below |
| 66 | `end_flags` | `uint16` | 2 | bit field | Bit 0 means clean finalization |
| 68 | `reserved0` | `uint32` | 4 | zero | Future expansion |
| 72 | `total_record_count` | `uint64` | 8 | records | Includes END |
| 80 | `trace_batch_count` | `uint64` | 8 | batches | Successfully written |
| 88 | `trace_count` | `uint64` | 8 | traces | Successfully written |
| 96 | `raw_sample_count` | `uint64` | 8 | bytes/samples | Native samples written |
| 104 | `bytes_before_end` | `uint64` | 8 | bytes | END prefix offset |
| 112 | `final_file_bytes` | `uint64` | 8 | bytes | Includes END |
| 120 | `gap_count` | `uint64` | 8 | gaps | GAP records written |
| 128 | `lost_trace_count` | `uint64` | 8 | traces | Exact plus best estimates |
| 136 | `config_record_count` | `uint64` | 8 | configs | Config records written |
| 144 | `duration_ns` | `uint64` | 8 | ns | Stop monotonic minus start |
| 152 | `rolling_crc32c` | `uint32` | 4 | CRC32C | All bytes before END |
| 156 | `reserved1` | `uint32` | 4 | zero | Future expansion |

Stop reasons:

| Value | Name |
|---:|---|
| 1 | `USER_STOP` |
| 2 | `FIXED_DURATION` |
| 3 | `FILE_SIZE_LIMIT` |
| 4 | `LOW_DISK` |
| 5 | `WRITER_OVERRUN` |
| 6 | `DEVICE_DISCONNECT` |
| 7 | `BACKEND_SHUTDOWN` |
| 8 | `WRITER_ERROR` |
| 9 | `START_FAILURE` |

A clean END may still report gaps. Clean means the writer deliberately
finalized the file and all summary fields are complete, not that no trace was
lost.

## 11. Timing semantics and future playback

Five concepts remain separate:

- `sequence` defines acquisition trace order. It is the primary loss detector.
- `device_packet_timestamp_ns` preserves the device value but is not assumed
  to share the host epoch.
- `host_receipt_unix_ns` supports user-facing recording history.
- `host_receipt_monotonic_ns` provides stable intra-session deltas unaffected
  by wall-clock corrections.
- recording elapsed time is `host_monotonic - session_start_monotonic`.

Future playback should use host-monotonic deltas between received batches for
coarse packet pacing and `nominal_trace_period_ns` within a batch. Explicit
`GAP_RECORD`s preserve tune pauses and known loss intervals. Playback must not
claim device-clock accuracy.

All traces in a batch have one packet-level device timestamp. Version 1 does
not synthesize individual device timestamps. When timing flag bit 2 is set,
the reader may expose a nominal relative offset of
`trace_index * nominal_trace_period_ns`, clearly labeled as derived from
`PacketAcqTime / PacketFrame`.

## 12. Recorder architecture and ownership

Proposed package:

```text
backend/recording/
  __init__.py
  models.py       # API/status/config dataclasses and enums
  format.py       # constants, structs, CRC and validation
  storage.py      # paths, limits, free-space checks, atomic finalization
  writer.py       # sequential binary writer
  recorder.py     # lifecycle, queue, status and acquisition-facing offer
  reader.py       # sequential reader and validator
backend/tools/inspect_recording.py
```

Data flow:

```text
SAN-90 single-owner acquisition thread
    ├── existing spectrum / waterfall / AI consumers
    └── Recorder.offer_packet(...)       # no disk I/O, bounded
            ├── reserve bounded byte/item capacity without waiting
            ├── copy PacketFrame × FrameWidth uint8 once to immutable bytes
            └── enqueue ConfigAndBatch or Batch item
                    └── dedicated writer thread
                            ├── CRC32C
                            ├── buffered write/writev
                            ├── limits/free-space checks
                            └── flush/finalize
```

The SDK/simulator-owned NumPy view may be reused on the next source call. A
recording queue item therefore owns an immutable `bytes` snapshot produced by
one `ndarray.tobytes(order="C")` call after capacity reservation. That same
object is passed to `google-crc32c` and `os.write`; the writer does not
concatenate the bulk payload into another complete-record buffer. Queue
ownership is released only after the record is fully written. A buffer pool
was intentionally deferred because immutable bytes provides a simple safe
one-copy implementation for this milestone.

The existing realtime consumers run before the recorder branch. Queue
saturation cannot block or disable spectrum, spectrogram, AI GRAY8, Frequency
Scan, or IF-overflow handling.

`offer_packet` receives both:

1. native hardware mapping directly from the current `RTA_PlotInfo`; and
2. the software Amplitude Offset separately.

It must not derive the native offset from an already corrected float32 trace.

Both `SimulatorSource` and `San90Source` expose
`set_recording_sink(...)`. The real-source branch runs after the existing
spectrum, waterfall, and AI consumers while the SDK packet view is still
valid. It passes native `RTA_PlotInfo.ScaleTodBm` and `OffsetTodBm` separately
from software Amplitude Offset, then the recorder makes its single immutable
ownership copy. A recorder rejection or exception is contained and cannot
stop the existing acquisition consumers.

## 13. Configuration ordering

The acquisition owner is the only trace producer. For each accepted packet:

1. Build a decode fingerprint from generation, verified frequency range, RBW,
   VBW validity/value, frame width, FFT size, reference level, native
   scale/offset, software Amplitude Offset, and interpretation-relevant enums.
2. Quantize values to their on-disk binary32/binary64 representation, then
   compare the packed fingerprint with the active fingerprint.
3. If different, allocate the next `config_id` and create one queue item that
   atomically contains `CONFIG_RECORD + TRACE_BATCH_RECORD`.
4. Reserve queue bytes for both before copying samples.
5. The writer writes the config first and the batch second.
6. Otherwise enqueue only the trace batch referencing the active config.

This prevents out-of-order config/trace writes without coordination between
threads. Duplicate records are avoided by comparing the exact packed
representation that a reader will receive; changes smaller than the stored
precision do not generate a useless config, while any decode-visible change
does. A repeated identical snapshot does not create a config.

A tune transaction emits `GAP_RECORD(RECONFIGURATION_PAUSE)` followed by the
new config/batch bundle. Frequency Scan naturally produces repeated configs
in one file; it does not create one file per frequency.

## 14. Queue and overrun policy

Default limits:

- maximum owned payload bytes: 64 MiB;
- maximum queued items: 256;
- warning high-water mark: 70%;
- critical mark: 90%;
- sustained overrun: a continuously pending rejected range for 250 ms or
  16 MiB of rejected payload since the queue last accepted a packet,
  whichever occurs first.

Both byte and item limits apply. At the measured approximately 25.45 MB/s raw
rate, 64 MiB represents about 2.5 seconds of native samples, excluding small
headers.

`offer_packet` never waits for a queue slot. When no buffer/byte reservation is
available:

1. do not copy the packet;
2. increment dropped batch/trace/sample counters immediately;
3. coalesce its sequence and timestamps into a small out-of-band pending-gap
   accumulator;
4. attach that gap atomically before the next retained batch;
5. if saturation is sustained, request stop with `WRITER_OVERRUN`.

The stop request is an out-of-band state flag, so it does not need a free data
queue slot. The writer drains already-owned data, writes the pending gap, then
writes END when storage remains usable. If disk I/O itself has failed, the
`.part` file and in-memory status are the evidence; a GAP/END cannot be
promised after the failed write.

Exposed counters:

- queue bytes/items and fill ratio;
- high-water bytes/items;
- enqueued/written/rejected batches;
- written traces/raw samples;
- gap/lost trace counts;
- total/file bytes and write throughput;
- last write latency, last error, and stop reason.

## 15. Recorder state machine

```text
IDLE
  └─ start ─> STARTING
                 ├─ header/session/config ready ─> RECORDING
                 └─ failure ─> FAILED

RECORDING
  ├─ stop/limit/disconnect/shutdown ─> STOPPING
  └─ fatal writer error ─> FAILED

STOPPING
  └─ producer detached, queue sealed ─> FINALIZING

FINALIZING
  ├─ END + flush + fsync + rename ─> COMPLETED
  └─ write/rename failure ─> FAILED (.part retained)

COMPLETED or FAILED
  └─ next valid start ─> STARTING
```

Only one session may be active. Concurrent starts return conflict. Stop is
idempotent: repeated calls retain the first highest-precedence stop reason and
wait on the same completion handle. Start and stop status transitions are
protected by one lifecycle lock; trace counters use a short lock or immutable
snapshot replacement. No API thread calls the SDK.

Device disconnect seals input and requests stop. Backend shutdown requests
`BACKEND_SHUTDOWN`, detaches the producer, and gives the writer a bounded
finalization deadline. If the deadline expires, the process leaves a
recoverable `.part`.

## 16. Storage, naming, and finalization

The service owns one configured recording root. A requested output directory
must resolve inside that root and must be an existing writable directory on
the same filesystem used for final rename. Prefixes must match:

```text
[A-Za-z0-9][A-Za-z0-9._-]{0,63}
```

Path separators, `..`, control characters, symlink escapes, and empty prefixes
are rejected. Files are opened with exclusive creation and mode `0600`.
Timestamp plus eight UUID hex characters prevents collisions. Existing files
are never overwritten.

Linux finalization uses `renameat2(RENAME_NOREPLACE)` in the same directory.
A portable fallback may use same-filesystem hard-link-plus-unlink semantics;
it must not use overwrite-capable `os.replace` on an arbitrary existing final
path.

Clean completion order:

1. stop accepting acquisition packets;
2. drain the queue and pending gap;
3. write the stop event and END;
4. flush Python/userspace buffers;
5. `fsync` the file;
6. close the descriptor;
7. finalize without overwrite from `.part` to `.san90rta`;
8. optionally `fsync` the parent directory.

The writer checks `statvfs` at start, at least every 250 ms while active, and
after each 64 MiB written. Default free-space reserve is 2 GiB and is
configurable.

Stop-condition precedence is:

1. writer/disk error;
2. low-disk reserve;
3. hard file-size limit;
4. fixed duration;
5. manual stop.

The implemented precedence inserts `WRITER_OVERRUN`, `DEVICE_DISCONNECT`, and
`BACKEND_SHUTDOWN` between the hard file-size limit and fixed-duration stop.
`START_FAILURE` and `WRITER_ERROR` share the highest failure class. Thus disk
or writer failure overrides every normal stop; low disk overrides file size;
file size overrides overrun/disconnect/shutdown; and all of those override
fixed/manual completion.

The writer reserves 4 KiB inside the hard size limit for a final event and END.
Before accepting a next record it predicts:

```text
current bytes + next total_record_length + finalization reserve
```

and stops before exceeding the limit when practical. A minimum file-size
limit must accommodate the file header, session metadata, first config, and
finalization reserve.

On power loss or crash the `.part` remains. A reader validates sequentially
and reports all complete records before the first truncated, invalid-length,
or CRC-failing record. It does not silently scan forward past corruption,
because a false `S9RR` inside raw payload could manufacture data. A future
salvage command should write a new file from the valid prefix and never modify
the original.

## 17. Reader and inspection API

Proposed interface:

```python
class San90RtaReader:
    def read_header(self) -> FileHeader: ...
    def iter_records(self) -> Iterator[Record]: ...
    def iter_configurations(self) -> Iterator[ConfigurationRecord]: ...
    def iter_trace_batches(self) -> Iterator[TraceBatchRecord]: ...
    def validate(self, *, verify_payload_crc: bool = True) -> ValidationReport: ...
    def reconstruct_dbm(
        self, batch: TraceBatchRecord, trace_index: int
    ) -> numpy.ndarray: ...
```

Iteration is streaming. It reads fixed headers first, validates lengths before
allocation, and exposes a bounded payload view or chunked reader. A playback
implementation must not require loading the full recording.

The CLI:

```bash
python3 backend/tools/inspect_recording.py FILE
```

Default output reports:

- format version, UUID and file size;
- device/application/session metadata;
- clean finalization or recoverable incomplete prefix;
- start/end/duration and stop reason;
- records, batches, traces, samples, gaps and lost traces;
- config IDs and analyzer generations;
- frequency ranges, point counts, FFT sizes and RBW values;
- first/last sequences and discontinuities;
- header/payload checksum failures;
- first invalid byte offset.

Useful options:

```text
--json
--no-payload-crc
--list-configs
--export-trace RECORD_INDEX:TRACE_INDEX --csv OUTPUT
```

CSV export reconstructs frequency and dBm with the referenced configuration.
It applies software Amplitude Offset once.

Reader invariants include:

- one session metadata record before data;
- monotonically increasing record index;
- config before every referencing trace;
- matching generation and frame width;
- monotonic `config_id`;
- exact trace payload size;
- sequence continuity or an explanatory GAP;
- END counters equal observed counters;
- no records after END.

## 18. Backend configuration and API

Preferences are stored atomically in `config/recording.json` with schema
version 1. Runtime state is never persisted and recording never auto-starts.
The backend-owned root defaults to `~/SAN90_Recordings`, outside the Git
repository, and may be overridden at process startup with
`SAN90_RECORDING_ROOT`. API clients may select only a safe relative
subdirectory below that root. Defaults are fixed mode, 5 seconds, a 4 GiB file
limit, a 2 GiB free-space reserve, output directory `.`, and prefix
`SAN90_RTA`.

Configuration model:

```json
{
  "mode": "fixed",
  "duration_s": 5.0,
  "file_size_limit_bytes": 4294967296,
  "free_disk_reserve_bytes": 2147483648,
  "output_directory": ".",
  "file_prefix": "SAN90_RTA"
}
```

`mode` is `fixed` or `manual`. Fixed requires a finite positive duration.
Manual has no duration but still obeys size, disk, disconnect, shutdown, and
writer-overrun stops.

Status model:

```json
{
  "state": "recording",
  "session_uuid": "4f17c290-...",
  "file_path": "...san90rta.part",
  "elapsed_s": 3.2,
  "written_bytes": 184320000,
  "trace_count": 24170,
  "batch_count": 100,
  "gap_count": 0,
  "lost_trace_count": 0,
  "queue_fill_ratio": 0.08,
  "queue_bytes": 5242880,
  "write_rate_bytes_s": 58000000,
  "stop_reason": null,
  "last_error": null
}
```

Implemented endpoints are:

- `GET /api/analyzer/recording/config`
- `PUT /api/analyzer/recording/config`
- `GET /api/analyzer/recording/directories`
- `POST /api/analyzer/recording/directories`
- `POST /api/analyzer/recording/start`
- `POST /api/analyzer/recording/stop`
- `GET /api/analyzer/recording/status`
- `GET /api/analyzer/recordings`
- `GET /api/analyzer/recordings/{recording_id}`
- `GET /api/analyzer/playback/status`
- `POST /api/analyzer/playback/open`
- `POST /api/analyzer/playback/play`
- `POST /api/analyzer/playback/pause`
- `POST /api/analyzer/playback/stop`

The directory endpoints back the Record-panel folder chooser. They expose only
relative directories under the configured backend-owned root and can create
nested relative directories without following symlinks. They are intentionally
not a general host filesystem browser.

The normal analyzer status response also includes a low-rate recording status
snapshot. The binary spectrum protocol is unchanged.

## 19. Recording bandwidth

Raw bandwidth is:

```text
trace_rate * frame_width * 1 byte
```

The verified 2026-07-20 profiles all produce approximately the same raw
point rate:

| Points | Measured traces/s | Raw MB/s | Raw GB/min | Raw GB/hour |
|---:|---:|---:|---:|---:|
| 26 | 979,040 | 25.455 | 1.527 | 91.638 |
| 52 | 489,252 | 25.441 | 1.526 | 91.588 |
| 104 | 244,764 | 25.455 | 1.527 | 91.640 |
| 208 | 122,382 | 25.455 | 1.527 | 91.640 |
| 416 | 61,191 | 25.455 | 1.527 | 91.640 |
| 832 | 30,595.5 | 25.455 | 1.527 | 91.640 |
| 1,664 | 15,297.5 | 25.455 | 1.527 | 91.638 |
| 3,328 | 7,647.5 | 25.451 | 1.527 | 91.623 |

These are decimal MB/GB. The corresponding rate is approximately
24.27 MiB/s and 85.3 GiB/hour. Record overhead is:

```text
136 bytes * SDK packet-call rate
```

plus occasional config/events. Its fraction for one batch is
`136 / (trace_count * frame_width)`. The writer keeps one SDK packet per
record in milestone 1 to preserve packet timing and simplifies recovery.
Buffered writes or `writev` avoid one system call per small header.

A short 512 MiB write-plus-`fsync` check on the current ext4 NVMe filesystem
measured 2,150.8 MB/s. This is about 84 times the native raw requirement, so
the current disk has ample short-run bandwidth headroom. It is not a
long-duration sustained-write or thermal test. At the current 391 GiB free,
theoretical raw capacity is roughly 4.6 hours before filesystem reserve and
other data.

The production dependency is `google-crc32c>=1.5`; focused validation used
version 1.8.0 with its C extension. A short 2026-07-29 128 MiB benchmark
measured:

- NumPy-to-immutable-`bytes` ownership copies: 2,802.9 MB/s;
- CRC32C of the retained `bytes`: 17,984.1 MB/s;
- sequential writer plus CRC32C, END, and `fsync`: 1,393.7 MB/s.

For comparison, passing `bytearray` or `memoryview` to the format abstraction
measured 3,703.1 MB/s and 10,393.4 MB/s respectively because version 1.8.0
requires conversion to immutable bytes. The recorder therefore owns `bytes`
at enqueue time and avoids this additional checksum conversion. The short
writer result is about 54.8 times the expected 25.45 MB/s native raw rate; it
is not a long-duration thermal/storage guarantee.

Compression is deferred. RF noise-like `uint8` traces may compress poorly,
and no representative-data benchmark currently demonstrates enough benefit
to justify CPU and latency risk.

## 20. Test plan

### Format unit tests

- exact `struct.size` and field offsets for file header and every record;
- file header pack/unpack and CRC;
- pack/unpack every record type;
- empty and non-empty payload CRC32C;
- unknown record skipping;
- invalid major version and byte-order marker rejection;
- maximum/header/total length enforcement;
- truncated prefix, header, and payload detection;
- payload-size arithmetic overflow and mismatch rejection;
- config-before-trace and frame-width/generation checks;
- sequence continuity and explicit gaps;
- clean END counters and rolling CRC;
- incomplete `.part` valid-prefix recovery.

### Recorder tests

- single active session and duplicate-start conflict;
- idempotent repeated stop;
- fixed-duration and manual stop;
- predicted file-size stop with finalization reserve;
- mocked low-disk condition;
- partial write, `fsync`, and rename errors;
- buffer-pool/queue overrun with a written GAP;
- sustained overrun stop;
- device disconnect and backend shutdown;
- same-generation mapping/Amplitude Offset config transition;
- new-generation Frequency Scan transition;
- identical config snapshot does not duplicate CONFIG;
- config-and-first-batch ordering under writer delay;
- existing spectrum, waterfall, AI and IF-overflow consumers still receive
  the same native packet.

### Reader tests

- valid one- and multi-generation files;
- unknown optional records;
- streaming iteration without whole-file allocation;
- reconstruct frequency axis and dBm;
- apply Amplitude Offset once;
- identify unexplained and explained sequence gaps;
- recover complete records from a truncated `.part`;
- report the exact first-invalid offset and checksum kind;
- reject invalid magic, version, config reference, and END summary.

### Short integration tests

1. Simulator fixed-frequency recording, inspect, and export one trace.
2. Simulator Frequency Scan recording across at least three configurations.
3. Inject writer delay to force a transient explicit GAP and sustained stop.
4. Short real-hardware fixed/manual, tune, scan, mapping, and controlled
   disconnect recordings with reader validation and no added acquisition
   errors.

No long hardware recording is required for the first implementation
milestone.

## 21. Acceptance checklist and open SDK questions

Version 1 satisfies the design acceptance criteria when implementation tests
prove:

- unambiguous native payload dimensions and decode mapping;
- config-before-trace ordering across scan/tune changes;
- detectable corruption/truncation and valid-prefix recovery;
- non-blocking acquisition enqueue and explicit loss accounting;
- correct limit/finalization behavior;
- streaming inspection and future playback pacing inputs.

Open SDK limitations remain:

- `TraceTimestampStep` units are not documented for this SAN-90; the observed
  value is a device-timer count, not seconds.
- The exact semantic position of `MeasAuxInfo.nsSinceEpoch` within a
  multi-trace packet should be confirmed with HAROGIC.
- Device timestamps are not assumed to be host-epoch aligned.
- Per-trace device timestamps are unavailable; only a nominal relative period
  can be derived from `PacketAcqTime / PacketFrame`.
- IF AGC may change mapping/telemetry without a generation change; the
  implementation therefore tests mapping fingerprints per received packet.
- Some firmware/API/FPGA/MCU/UID fields may be unavailable and must remain
  null rather than inferred.
