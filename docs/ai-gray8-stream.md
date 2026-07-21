# SAN-90 GRAY8 AI image stream

The AI stream is an independent output branch for an external inference service. It contains no YOLO model and does not modify the existing 60 FPS spectrum, 60-row/s minimum-RBW waterfall, browser WebSocket, or two-slot display snapshot exchange.

## Acquisition integration

The SAN-90 owner thread calls `RTA_GetRealTimeSpectrum_Raw` once and creates one zero-copy NumPy `uint8` view shaped `(PacketFrame, FrameWidth)`. Existing native temporal-spectrum and max-hold waterfall consumers run first. The same packet view, `RTA_PlotInfo.ScaleTodBm`, `RTA_PlotInfo.OffsetTodBm`, frequencies, and trace interval are then offered to `AiStreamPipeline`.

The AI accumulator converts the complete SDK packet to absolute float32 dBm in a reusable packet buffer. Deterministically selected 640-trace windows are linearly resampled to 640 frequency positions directly into a preallocated image buffer. Interpolation preserves the first and last SDK bins. Every row inside an image is consecutive and chronological; complete 640-row windows between selected images may be skipped to hold 7–10 image/s without throttling hardware.

Only vectorized conversion/interpolation, buffer ownership changes, and non-blocking queue operations occur on the SDK thread. GRAY8 normalization, statistics, JSON serialization, ZeroMQ transmission, and optional PNG/JSON writing run on `san90-ai-publisher`.

## Image contract

| Property | Value |
|---|---|
| Pixel format | `GRAY8` |
| Shape | `(640, 640)` |
| Type/channels | contiguous C-order `numpy.uint8`, one channel |
| Payload | exactly 409,600 raw bytes |
| Horizontal direction | start frequency to stop frequency |
| Vertical direction | oldest trace at row 0, newest trace at row 639 |

There is no image header, axes, labels, colormap, timestamp drawing, or bounding boxes.

## Fixed power profiles

| Profile | Minimum | Maximum |
|---|---:|---:|
| `normal` | -130 dBm | -50 dBm |
| `external_lna` (default) | -120 dBm | -20 dBm |
| `strong_signal` | -100 dBm | 0 dBm |

The fixed mapping is `clip(rint((dBm - min_dBm) * 255 / (max_dBm - min_dBm)), 0, 255)`. Per-image min/max, percentile scaling, histogram equalization, AGC, and adaptive contrast are prohibited because they make identical RF power produce different pixels. Image extrema and clipping ratios are diagnostic only.

## Configuration

| Environment variable | Default |
|---|---|
| `AI_STREAM_ENABLED` | `true` |
| `AI_TARGET_IMAGES_PER_SECOND` | `10.0` (validated 7–10) |
| `AI_IMAGE_WIDTH`, `AI_IMAGE_HEIGHT`, `AI_TRACES_PER_IMAGE` | `640` each |
| `AI_POWER_PROFILE` | `external_lna` |
| `AI_STREAM_BIND` | `tcp://0.0.0.0:5557` |
| `AI_QUEUE_SIZE`, `AI_BUFFER_POOL_SIZE` | `2`, `4` |
| `AI_DROP_POLICY` | `drop_oldest` |
| `AI_PREVIEW_ENABLED` | `false` |
| `AI_PREVIEW_DIRECTORY` | `data/ai_preview` |
| `AI_PREVIEW_SAVE_INTERVAL_SECONDS`, `AI_PREVIEW_MAX_FILES` | `1.0`, `20` |
| `AI_SEND_HIGH_WATER_MARK`, `AI_SEND_TIMEOUT_MS`, `AI_SOCKET_LINGER_MS` | `2`, `5`, `0` |
| `AI_CLIPPED_HIGH_WARNING_RATIO` | `0.001` |

Dimensions are validated as exactly 640. An invalid startup profile is rejected. A rejected runtime profile leaves the prior valid profile active. Profile changes are snapshotted only when a new image starts.

```bash
python3 -m pip install --user -r backend/requirements.txt
npm run backend:start
npm run frontend:start

wget -qO- http://127.0.0.1:8000/api/ai-stream/status
wget -qO- --method=PUT --header='Content-Type: application/json' \
  --body-data='{"profile":"normal"}' http://127.0.0.1:8000/api/ai-stream/power-profile
wget -qO- --method=PUT --header='Content-Type: application/json' \
  --body-data='{"enabled":false}' http://127.0.0.1:8000/api/ai-stream/enabled
```

## ZeroMQ protocol

The complete field-level specification is [ai-gray8-protocol.md](ai-gray8-protocol.md).

SAN-90 uses `PUSH`/bind; the AI service uses `PULL`/connect. Each message has exactly two parts:

1. UTF-8 JSON with `protocol_version: 1` and `message_type: san90_gray8_waterfall`.
2. The exact 409,600-byte contiguous GRAY8 buffer.

Metadata includes sequence, host-epoch capture timestamps, trace sequence range, frequency range, source/output widths, configuration generation, exact profile limits, clipping ratios, and dBm extrema. Host monotonic time controls rate selection. Host epoch plus the SDK-derived trace interval describes capture time because this firmware's auxiliary device epoch value was measured moving backward between packet boundaries.

No receiver is a normal state. `IMMEDIATE`, a send HWM of two, non-blocking sends, finite timeout, and zero linger cause drops rather than waits. The SDK thread never accesses ZeroMQ.

```python
import json
import numpy as np
import zmq

context = zmq.Context.instance()
socket = context.socket(zmq.PULL)
socket.connect("tcp://127.0.0.1:5557")

while True:
    metadata_bytes, payload = socket.recv_multipart()
    metadata = json.loads(metadata_bytes.decode("utf-8"))
    if len(payload) != 640 * 640:
        continue
    image = np.frombuffer(payload, dtype=np.uint8).reshape(640, 640)
```

If a downstream adapter needs three channels it may use `np.repeat(image[:, :, None], 3, axis=2)`. SAN-90 transport remains single-channel.

## Receiver and previews

```bash
python3 tools/ai_gray8_receiver.py
python3 tools/ai_gray8_receiver.py --save-dir ./received_preview --save-every 10 --max-files 20
python3 tools/ai_gray8_receiver.py --display  # optional OpenCV
```

The receiver validates metadata/payloads, reports rates/statistics, and skips malformed messages. Saved PNGs are lossless grayscale mode `L` with matching JSON.

For publisher previews, set `AI_PREVIEW_ENABLED=true`. At most one PNG/JSON pair per interval is written and old pairs rotate out. `GET /api/ai-stream/preview.png` returns the latest cached PNG only when requested.

## Metrics and validation

`GET /api/ai-stream/status` exposes trace/image totals, rate-limit skips, queue/no-buffer/send drops, queue/pool depth, rolling created/sent FPS, timing, clipping, and extrema. High clipping emits a rate-limited warning but never changes profile automatically.

```bash
python3 -m unittest discover -s tests -v
python3 backend/tools/benchmark_ai_stream.py --duration 60
python3 backend/tools/benchmark_ai_stream.py --duration 600
```

The benchmark feeds about 7,600 traces/s through the actual temporal-spectrum, waterfall, and AI accumulator classes. It fails unless acquisition stays within 2%, both display producers remain approximately 60/s, AI stays 7–10.2/s, and queues remain bounded.
