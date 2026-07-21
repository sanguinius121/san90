# AI GRAY8 multipart protocol v1

Transport is ZeroMQ `PUSH` (SAN-90 bind) to `PULL` (consumer connect), default `tcp://0.0.0.0:5557`. Every message contains exactly two parts in this order.

## Part 1: UTF-8 JSON

```json
{
  "protocol_version": 1,
  "message_type": "san90_gray8_waterfall",
  "source": "SAN-90",
  "sequence": 12345,
  "timestamp_ns": 1784600000100000000,
  "width": 640,
  "height": 640,
  "channels": 1,
  "pixel_format": "GRAY8",
  "dtype": "uint8",
  "memory_order": "C",
  "payload_size_bytes": 409600,
  "center_frequency_hz": 2450000000.0,
  "start_frequency_hz": 2399218750.0,
  "stop_frequency_hz": 2500781250.0,
  "power_profile": "external_lna",
  "power_min_dbm": -120.0,
  "power_max_dbm": -20.0,
  "db_per_gray_level": 0.39215686274509803,
  "trace_count": 640,
  "first_trace_sequence": 8000000,
  "last_trace_sequence": 8000639,
  "capture_start_timestamp_ns": 1784600000000000000,
  "capture_end_timestamp_ns": 1784600000083800000,
  "frame_width_source": 3328,
  "frame_width_output": 640,
  "configuration_generation": 1,
  "clipped_low_ratio": 0.001,
  "clipped_high_ratio": 0.0002,
  "image_min_dbm": -126.4,
  "image_max_dbm": -18.7
}
```

`timestamp_ns` equals the capture-end host epoch timestamp. Capture start/end describe the first and last trace, not queue or send time. `first_trace_sequence..last_trace_sequence` is inclusive and always contains exactly 640 consecutive trace identities. `frame_width_source` is the native RTA width; `frame_width_output` is always 640.

Clipping ratios use `<= power_min_dbm` and `>= power_max_dbm`. The image statistics never alter the fixed profile.

## Part 2: raw pixels

Part 2 is exactly 409,600 bytes with no header or compression:

```python
image = np.frombuffer(payload, dtype=np.uint8).reshape(640, 640)
```

Row 0 is the oldest trace. Row 639 is the newest. Column 0 corresponds to `start_frequency_hz`; column 639 corresponds to `stop_frequency_hz`.

Consumers must reject unsupported versions/types, non-finite frequency or power metadata, incorrect dimensions/format, messages with other than two parts, and payloads whose length is not exactly 409,600 bytes.
