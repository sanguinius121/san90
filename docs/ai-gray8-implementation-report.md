# GRAY8 AI stream implementation report

Completed and hardware-validated 2026-07-21 with SAN-90 MCU/FPGA 0.55.103 and HTRA API 0.55.88.

## Existing path and integration point

`San90Source._acquire_packet_on_owner()` is the sole device read path. It calls `RTA_GetRealTimeSpectrum_Raw`, exposes the SDK-owned buffer as a zero-copy contiguous NumPy `uint8` array shaped `(PacketFrame, FrameWidth)`, validates it, and constructs `RawAmplitudeMapping` from `RTA_PlotInfo.ScaleTodBm` and `OffsetTodBm`.

The new branch is one call immediately after the existing `NativeSpectrumTemporalAccumulator` and `TimedWaterfallBatchProducer` calls. It uses the same packet view and metadata. There is no second open, SDK reader, bus trigger, frontend waterfall, or WebSocket path. Existing display consumers remain native `uint8`; their intentionally sparse 60 Hz float conversion was not replaced by an all-trace float display path.

The AI accumulator converts each complete packet once into a reusable float32 packet buffer. Selected complete 640-trace windows are frequency-resampled into one of four preallocated 640×640 float buffers. Completed buffers enter a two-item non-blocking drop-oldest queue. A separate `san90-ai-publisher` worker computes fixed-profile GRAY8, statistics, JSON, ZeroMQ output, and previews, then returns buffer ownership.

## Configuration and protocol

Configuration and operating instructions are in [ai-gray8-stream.md](ai-gray8-stream.md). The exact two-part JSON/raw protocol is [ai-gray8-protocol.md](ai-gray8-protocol.md).

The output is one-channel, C-contiguous `uint8` with shape `(640, 640)` and an exact 409,600-byte payload. Row 0 is oldest and row 639 newest. Three immutable normalization choices are available: `normal` (-130/-50 dBm), `external_lna` (-120/-20 dBm, default), and `strong_signal` (-100/0 dBm).

## Hardware measurements

At the minimum-RBW profile, before and after enabling the branch:

| Metric | AI disabled | AI enabled |
|---|---:|---:|
| SDK traces/s | 7,629.4 | 7,628.9 |
| Spectrum producer | 59.9–60.0 FPS | 59.9–60.0 FPS |
| Frontend waterfall | 59.9–60.0 rows/s | 59.9–60.0 rows/s |
| Waterfall batches | 59.9–60.0/s | 59.9–60.0/s |
| Browser spectrum/spectrogram | established 59–60 / 59–60 FPS | 59 / 59 FPS sampled |
| Backend CPU | 35.3–38.1%, mean 36.5% of one core | 34.8–45.9%, mean 41.2% |
| Backend RSS | 97.2 MiB | 114.1 MiB |
| AI images created | 0 | approximately 9.6–10.0/s |
| AI normalization | n/a | 0.76–1.48 ms/image sampled |
| Queue/no-buffer drops | n/a | 0 / 0 |

The roughly 16.9 MiB RSS increase is the committed subset of the fixed buffer pool and packet/interpolation workspaces. Native acquisition changed by less than 0.01%. The browser reported zero replaced, stale, malformed, out-of-order, or sequence-gap display data.

A real ZeroMQ PULL receiver measured 9.94–10.08 images/s. Every multipart payload validated as exactly 409,600 bytes and reconstructed to `(640, 640)` `uint8`. Hardware captures covered 640 consecutive traces in approximately 83.6–83.8 ms. With no receiver, non-blocking sends were counted as send drops while acquisition and the UI continued normally.

The installed firmware's auxiliary device epoch timestamp was observed moving backward at packet boundaries. Image-rate scheduling therefore uses host monotonic time. Transmitted capture timestamps use host epoch time combined with the SDK-derived trace interval, producing positive chronological capture durations. SDK trace sequence order remains the row-identity source.

### All eight RBW profiles with AI enabled

| Index | Points | Actual RBW | SDK traces/s | Spectrum FPS | Waterfall rows/s | AI created FPS | Queue/buffer drops |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 26 | 7.719180 MHz | 974,880 | 60 | 480 | 10 | 0 / 0 |
| 1 | 52 | 3.859590 MHz | 487,081 | 60 | 480 | 10 | 0 / 0 |
| 2 | 104 | 1.929795 MHz | 243,733 | 60 | 480 | 10 | 0 / 0 |
| 3 | 208 | 964.897 kHz | 121,604 | 60 | 480 | 10 | 0 / 0 |
| 4 | 416 | 482.449 kHz | 60,844 | 60 | 480 | 10 | 0 / 0 |
| 5 | 832 | 241.224 kHz | 30,427 | 60 | 240 | 10 | 0 / 0 |
| 6 | 1,664 | 120.612 kHz | 15,228 | 60 | 120 | 10 | 0 / 0 |
| 7 | 3,328 | 60.306 kHz | 7,620 | 60 | 60 | 9–10 | 0 / 0 |

Auto RBW was restored, acquisition stopped, the device closed, the USB handoff reset completed, and an immediate reopen succeeded. Backend and frontend were returned to their initially stopped state.

## Ten-minute synthetic soak

`benchmark_ai_stream.py --duration 600` fed the actual native temporal-spectrum, timed waterfall, and AI accumulator implementations at a nominal 7,600 traces/s:

| Metric | Result |
|---|---:|
| Elapsed | 600.038 s |
| Traces processed | 4,560,000 |
| Acquisition | 7,599.52 traces/s |
| Spectrum | 59.363 frames/s |
| Waterfall | 59.996 rows/s |
| AI output | 9.9994 images/s |
| AI images | 6,000 |
| Queue/no-buffer drops | 0 / 0 |
| Final queue/free buffers | 0 / 4 |
| CPU | 14.53% of one core |
| RSS start/end | 31.37 / 48.45 MiB |

RSS reached approximately 48.3 MiB during initial buffer commitment and remained at that plateau when sampled around 2, 4, 5, and 7.5 minutes. There was no queue, buffer, or process-memory growth.

## Files

Added:

- `backend/ai_stream/{config,image_accumulator,image_publisher,metrics,pipeline,power_profiles,preview,protocol}.py`
- `backend/tools/benchmark_ai_stream.py`
- `tools/ai_gray8_receiver.py`
- `tests/test_ai_stream.py`
- `docs/ai-gray8-stream.md`
- `docs/ai-gray8-protocol.md`
- this report

Modified:

- `backend/analyzer/san90.py`
- `backend/api/service.py`
- `backend/main.py`
- `backend/requirements.txt`
- `README.md`
- `.gitignore`

## Verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm test
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm run lint
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm run build
python3 backend/tools/benchmark_ai_stream.py --duration 600
python3 tools/ai_gray8_receiver.py --connect tcp://127.0.0.1:5557
```

Results: 81 Python tests passed, 58 TypeScript tests passed, ESLint passed, and the production Vite/TypeScript build passed. Tests cover profiles, conversion, resizing above/below/equal to 640, chronology across packets, 7/10 Hz scheduling, fixed GRAY8 mapping, metadata, clipping, drop-oldest/no-buffer paths, buffer return, real no-receiver ZeroMQ behavior, exact two-part reconstruction, lossless preview/rotation, and invalid-profile rollback.

## Remaining limitations

- A successful PUSH send means ZeroMQ accepted the message; it does not acknowledge completion of external inference. Application-level acknowledgements would require a separate protocol.
- The transport has no encryption or authentication and should be exposed only on a trusted network unless a later deployment adds ZeroMQ security.
- Publisher-side preview is intentionally low-rate and disabled by default; it is not a browser inference feed.
- The 600-second soak is hardware-independent. Hardware was exercised live at all eight RBW points and through repeated close/reopen cycles, but not held for ten continuous minutes in this run.
