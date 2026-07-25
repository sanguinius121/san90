# Real-time analyzer binary protocol

All multi-byte fields are little-endian. Legacy current-spectrum and status messages retain the version-2 96-byte header. Batched waterfall messages use version 3. Combined temporal spectrum messages use version 4. Parsers continue accepting the legacy messages. The SAN-90 owner thread uses version 4 spectrum and version 3 waterfall messages by default.

| Offset | Type | Field |
|---:|---|---|
| 0 | `char[4]` | Magic `SAN9` |
| 4 | `uint8` | Protocol version (`2`) |
| 5 | `uint8` | Message type |
| 6 | `uint8` | Source: `1` simulator, `2` SAN-90 |
| 7 | `uint8` | Payload type: `1` float32, `2` uint8, `3` UTF-8 JSON |
| 8 | `uint16` | Header size (`96`) |
| 10 | `uint16` | Flags, currently zero |
| 12 | `uint64` | Application sequence |
| 20 | `uint64` | Device timestamp, preserved verbatim |
| 28 | `uint64` | Host Unix receipt timestamp |
| 36 | `uint64` | Configuration generation |
| 44 | `uint32` | Point count |
| 48 | `uint32` | Payload length in bytes |
| 52 | `float64` | Actual start frequency, Hz |
| 60 | `float64` | Actual center frequency, Hz |
| 68 | `float64` | Actual stop frequency, Hz |
| 76 | `float64` | Actual span, Hz |
| 84 | `float64` | Actual RBW, Hz |
| 92 | `float32` | Reference level, dBm |
| 96 | bytes | Payload begins |

The canonical struct format is:

```text
<4sBBBBHHQQQQII5df
```

This yields 96 bytes. Parsers must use the transmitted `header_size`, not hard-coded payload offsets. The Python `struct.calcsize` result and TypeScript parser are tested together.

Message types:

- `0x01`: current spectrum, contiguous little-endian float32 dBm, `point_count × 4` bytes.
- `0x02`, version 4: combined temporal spectrum; newest float32 trace followed by interval-maximum float32 trace.
- `0x03`, version 2: legacy interval native max-hold waterfall row, uint8, `point_count` bytes.
- `0x03`, version 3: native max-hold waterfall batch, contiguous row-major uint8, `row_count × point_count` bytes.
- `0x10`: runtime status, UTF-8 JSON. Point count and measurement fields in the JSON are authoritative for status.
- `0x11`: current-frame AI frequency detections, UTF-8 JSON with `point_count = 0`.
- `0x12`: reserved for device errors.

Validation requirements:

- magic, version, header size, message type, source, and payload type must be recognized;
- total byte length must equal `header_size + payload_length`;
- spectrum and waterfall payload lengths must match point count and dtype;
- frequency metadata must be finite with `stop > start` and `stop - start ≈ span`;
- spectrum values must be finite;
- `device_timestamp_ns` is not used for frame age because the connected SAN-90 clock is not aligned with host Unix time;
- host receipt time is used for logs/UI time, while local monotonic receipt time remains backend-internal for freshness and latency.

### Current-frame AI detections (`0x11`)

The backend's latest-only ZeroMQ subscriber receives one JSON result from
`tcp://127.0.0.1:5558`, validates it, and forwards it in the version-2 JSON
envelope. The payload is:

```json
{
  "sequence": 123,
  "timestamp_ns": 1784947230410329302,
  "generated_at": 1784947230.4379168,
  "received_at_ns": 1784947230439000000,
  "detections": [
    {
      "class_id": 4,
      "label": "DJI_20MHz",
      "confidence": 0.86,
      "frequency_start": 5731000000.0,
      "frequency_stop": 5751000000.0
    }
  ]
}
```

Each message replaces the prior current-frame result. `frequency_start` and
`frequency_stop` are absolute Hz values for that detection. The subscriber
does not forward or derive UI annotations from the detector's legacy
`label_freq_ranges_hz` history because that field may span old center-frequency
configurations. Client mailboxes retain at most one unsent `0x11` message.

The subscriber is enabled by default. `AI_DETECTION_SUB_URL` overrides the
endpoint, and `AI_DETECTION_SUB_ENABLED=false` disables it. ZeroMQ reconnect is
independent of analyzer acquisition.

## Version 3 waterfall batch header

| Offset | Type | Field |
|---:|---|---|
| 0 | `char[4]` | Magic `SAN9` |
| 4 | `uint8` | Protocol version (`3`) |
| 5 | `uint8` | Message type (`0x03`) |
| 6 | `uint8` | Source |
| 7 | `uint8` | Payload type (`2`, uint8) |
| 8 | `uint16` | Header size (`120`) |
| 10 | `uint16` | Flags, currently zero |
| 12 | `uint64` | Batch sequence |
| 20 | `uint64` | First row sequence |
| 28 | `uint64` | First row device timestamp |
| 36 | `uint64` | First row host Unix timestamp |
| 44 | `uint64` | Configuration generation |
| 52 | `uint64` | Nominal row period, ns |
| 60 | `uint32` | Row count |
| 64 | `uint32` | Point count per row |
| 68 | `uint32` | Payload length |
| 72 | `uint32` | Reserved, zero |
| 76 | `float64` | Actual start frequency, Hz |
| 84 | `float64` | Actual center frequency, Hz |
| 92 | `float64` | Actual stop frequency, Hz |
| 100 | `float64` | Actual span, Hz |
| 108 | `float64` | Actual RBW, Hz |
| 116 | `float32` | Reference level, dBm |
| 120 | bytes | `uint8[row_count][point_count]` payload |

The canonical struct format is `<4sBBBBHHQQQQQQIIII5df`. A normal fast-profile batch is four rows by 832 points: 3,328 payload bytes plus the 120-byte header. `row_count = 0`, `point_count = 0`, mismatched payload sizes, unsupported versions, non-finite metadata, and stale configuration generations are rejected.

## Version 4 temporal spectrum header

The temporal spectrum is one atomic, newest-data-first display interval. The payload contains `latest_trace_float32[point_count]` immediately followed by `interval_max_trace_float32[point_count]`. The maximum is accumulated in native `uint8` space before one conversion to dBm.

| Offset | Type | Field |
|---:|---|---|
| 0 | `char[4]` | Magic `SAN9` |
| 4 | `uint8` | Version `4` |
| 5 | `uint8` | Message `0x02` |
| 6 | `uint8` | Source |
| 7 | `uint8` | Payload type `4`, float32 pair |
| 8 | `uint16` | Header size `128` |
| 10 | `uint16` | Flags |
| 12 | `uint64` | Temporal sequence |
| 20 | `uint64` | Device timestamp, zero when unavailable |
| 28 | `uint64` | Host Unix timestamp |
| 36 | `uint64` | Configuration generation |
| 44 | `uint64` | Interval start, host monotonic ns |
| 52 | `uint64` | Interval end, host monotonic ns |
| 60 | `uint32` | Native traces integrated |
| 64 | `uint32` | Point count per trace |
| 68 | `uint32` | Payload bytes, exactly `point_count × 8` |
| 72 | `uint32` | Reserved |
| 76 | `float64` | Actual start frequency, Hz |
| 84 | `float64` | Actual center frequency, Hz |
| 92 | `float64` | Actual stop frequency, Hz |
| 100 | `float64` | Actual span, Hz |
| 108 | `float64` | Actual RBW, Hz |
| 116 | `float32` | Reference level, dBm |
| 120 | `float32` | Native-code scale to dBm |
| 124 | `float32` | Native-code offset to dBm |
| 128 | bytes | Latest trace then interval maximum |

The canonical struct is `<4sBBBBHHQQQQQQIIII5dfff` (128 bytes). A consumer that falls behind retains the newest current trace and merges interval maxima element-wise. It never grows a trace queue.

The protocol accepts every verified SAN-90 display width: 26, 52, 104, 208, 416, 832, 1,664, and 3,328 points. Point count is never expanded for visual smoothing. A 26-point temporal message carries exactly 52 float32 values: 26 newest values followed by 26 interval maxima.
