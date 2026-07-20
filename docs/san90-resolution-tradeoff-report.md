# SAN-90 eight-step resolution trade-off report

Implemented and hardware-validated 2026-07-20 against SAN-90 MCU/FPGA 0.55.103 and HTRA API 0.55.88. Auto RBW remains a separate safe mode. Manual mode exposes eight measured, deduplicated operating points ordered from time priority to frequency priority.

The canonical table is [`config/san90-resolution-tradeoff.json`](../config/san90-resolution-tradeoff.json). Backend capability serialization, simulator behavior, and the frontend slider all consume that same file.

## Final operating points

| Index | Requested RBW | Actual RBW | Points / FFT | Measured SDK traces/s | Bin spacing | Spectrum / WebGL | Waterfall rows/s | Rows/batch | Traces/row | Visible rows |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 8 MHz | 7.719180 MHz | 26 / 32 | 979,040 | 3.906250 MHz | 60 / 60 FPS | 480 | 8 | 2,039.67 | 2,400 |
| 1 | 4 MHz | 3.859590 MHz | 52 / 64 | 489,252 | 1.953125 MHz | 60 / 60 FPS | 480 | 8 | 1,019.28 | 2,400 |
| 2 | 2 MHz | 1.929795 MHz | 104 / 128 | 244,764 | 976.563 kHz | 60 / 60 FPS | 480 | 8 | 509.93 | 2,400 |
| 3 | 1 MHz | 964.897 kHz | 208 / 256 | 122,382 | 488.281 kHz | 60 / 60 FPS | 480 | 8 | 254.96 | 2,400 |
| 4 | 500 kHz | 482.449 kHz | 416 / 512 | 61,191 | 244.141 kHz | 60 / 60 FPS | 480 | 8 | 127.48 | 2,400 |
| 5 | 300 kHz | 241.224 kHz | 832 / 1,024 | 30,595.5 | 122.070 kHz | 60 / 60 FPS | 240 | 4 | 127.48 | 1,200 |
| 6 | 150 kHz | 120.612 kHz | 1,664 / 2,048 | 15,297.5 | 61.035 kHz | 60 / 60 FPS | 120 | 2 | 127.48 | 600 |
| 7 | 50 kHz | 60.306 kHz | 3,328 / 4,096 | 7,647.5 | 30.518 kHz | 60 / 60 FPS | 60 | 1 | 127.46 | 300 |

The widest five profiles are capped at 480 waterfall rows/s. Native acquisition is not throttled: the producer max-holds every native trace into the appropriate 2.083 ms display row. Spectrum publication uses one bounded v4 message per fixed 60 Hz interval containing both the newest trace and the max across every trace in that interval.

## Measured runtime validation

The following two-second steady-state samples were collected by `backend/tools/test_san90_eight_profiles.py` after fixing the interval scheduler to remain on a monotonic 60 Hz deadline grid.

| Index | SDK traces/s | Point rate | Temporal frames/s | Traces/spectrum frame | Waterfall rows/s | Traces/row | WS spectrum | WS waterfall | CPU | RSS start/end | Reconfigure |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 977,445 | 25.414 Mpoint/s | 59.5 | 16,291.18 | 480 | 2,035.19 | 19,992 B/s | 19,680 B/s | 45.28% | 64.39 / 64.41 MiB | 112.70 ms |
| 1 | 488,360 | 25.395 Mpoint/s | 60.0 | 8,139.33 | 480 | 1,017.29 | 32,640 B/s | 32,160 B/s | 45.39% | 64.43 / 64.43 MiB | 110.20 ms |
| 2 | 244,296 | 25.407 Mpoint/s | 59.5 | 4,074.35 | 480 | 508.70 | 57,120 B/s | 57,120 B/s | 43.79% | 64.44 / 64.44 MiB | 110.24 ms |
| 3 | 121,992 | 25.374 Mpoint/s | 59.5 | 2,034.55 | 480 | 254.32 | 106,624 B/s | 107,040 B/s | 37.90% | 64.51 / 64.51 MiB | 110.73 ms |
| 4 | 60,996 | 25.374 Mpoint/s | 59.5 | 1,017.28 | 480 | 127.14 | 205,632 B/s | 206,880 B/s | 35.85% | 64.51 / 64.51 MiB | 110.20 ms |
| 5 | 30,498 | 25.374 Mpoint/s | 59.5 | 508.64 | 240 | 127.16 | 403,648 B/s | 206,880 B/s | 36.43% | 64.51 / 64.51 MiB | 109.12 ms |
| 6 | 15,249 | 25.374 Mpoint/s | 59.5 | 254.32 | 120 | 127.13 | 799,680 B/s | 206,880 B/s | 35.68% | 64.54 / 64.54 MiB | 108.75 ms |
| 7 | 7,628.5 | 25.388 Mpoint/s | 59.5 | 127.25 | 60 | 127.18 | 1,591,744 B/s | 206,880 B/s | 38.52% | 64.62 / 64.62 MiB | 112.43 ms |

Waterfall output was 60 batches/s at all points. No temporal exchanges were replaced, no malformed messages were observed, incomplete state was discarded at generation boundaries, and RSS remained flat over each measurement interval.

An independent end-to-end test applied index 0 through REST and observed, over three seconds, 179 v4 spectrum-temporal messages (59.67/s), 180 v3 waterfall batches (60/s), and six status messages. Every message used the same configuration generation, 26 spectrum points, and eight waterfall rows per batch. Payload dimensions and generation metadata validated successfully.

## Integrity and viewport behavior

- SAN-90 acquisition stays at its natural hardware rate; no acquisition throttling or per-trace queue was introduced.
- The native `uint8` accumulator receives every SDK trace and computes both waterfall max-hold rows and the 60 Hz spectrum interval max without per-point Python loops.
- The spectrum exchange is bounded: late consumers replace old display intervals instead of growing a queue.
- Compatible displaced temporal frames merge only when generation, point count, frequency axis, scale, and offset match. Incompatible frames are rejected and counted.
- The temporal scheduler advances on a fixed monotonic deadline grid. Empty elapsed slots are counted and skipped; it never fabricates duplicated frames to catch up.
- Current spectrum uses the latest native trace; the companion interval-max trace retains short FHSS activity between renders.
- Configuration generation scopes RBW, calibration, point count, FFT size, timing, and frequency metadata. Reconfiguration clears incomplete rows/batches and the frontend rejects stale generations.
- Low-point profiles (26, 52, and 104 points) pass parser, buffer, marker, renderer-pool, and transition tests. Marker frequencies use bin centers.
- The visible spectrogram span is fixed at exactly 5.0 seconds. Visible rows are 2,400, 1,200, 600, or 300 according to row rate; the 4,096-row texture is storage, not display duration.

## Frontend behavior

Auto RBW hides the eight-stop slider. Switching to Manual stages the matching verified step without issuing a command. Dragging changes a local expected-value preview; pointer release or keyboard commit sends one safe transaction. The UI disables the control during reconfiguration and snaps to actual hardware readback. An unmatched advanced numeric RBW is represented as `Custom` rather than falsely selecting a step.

The preview and active status show requested and actual RBW, FFT and returned points, native trace rate, bin spacing, fixed 60 FPS spectrum target, waterfall row/batch rate, traces per row, row time, span, and the fixed five-second viewport.

Live trace and waterfall payloads never enter React state. WebGL listeners receive frames immediately, while Zustand UI statistics are summarized once per second and status messages update twice per second. The waterfall animation path retains at most sixteen batches (128 rows / approximately 267 ms at the fastest profile), drains all retained batches oldest-to-newest, and records replaced batches and rows if that finite limit is ever exceeded.

## Subphase B timing and stability

A 600-second direct owner-thread run held index 0 at the maximum hardware rate:

| Metric | Result |
|---|---:|
| SDK acquisition | 976,577.97 traces/s |
| Temporal publication | 59.99994 frames/s |
| Mean traces/temporal frame | 16,276.31 |
| Temporal frames completed | 36,000 |
| Missed temporal deadlines | 0 |
| Mean/max native-to-float conversion | 17.05 / 170.39 µs |
| Mean/max temporal finalization | 61.55 / 225.19 µs |
| Mean native max update per interval | 1.137 ms |
| Waterfall rows | 479.986 rows/s |
| Waterfall batches | 59.998 batches/s |
| Mean traces/waterfall row | 2,034.56 |
| Replaced waterfall batches/rows | 0 / 0 |
| Stale temporal/waterfall messages | 0 / 0 |
| Backend RSS | 65.26 → 65.30 MiB |

Three waterfall row deadlines were crossed among approximately 288,000 rows. No batch or row was replaced, and the producer continued on its monotonic grid. Nine repeated transitions through indices 7 → 0 → 4 produced only current-generation temporal frames, then Auto restoration and immediate reopen passed.

## GPU-backed browser validation

Firefox 130 ran non-headless on the target X11/Wayland display. Both spectrum and spectrogram acquired WebGL2 contexts reporting hardware vendor `Intel` and renderer `Intel(R) HD Graphics, or similar`; software SwiftShader was not used. The measured display callback cadence was approximately 99.35 Hz.

Initial GPU testing exposed two issues that were corrected before acceptance:

1. An elapsed-time scheduler aliased a roughly 100 Hz display down to approximately 50 FPS. Live 60 Hz producer data now renders on the next animation frame; interaction-only redraws remain on a drift-free 60 Hz deadline grid.
2. Per-message Zustand writes caused React to rebuild control UI at live frame cadence. Configuration state now changes only on actual metadata changes, and FPS/byte UI counters update once per second.

At the 26-point / 480-row/s profile, the final ten-minute run produced:

- spectrum render samples of 59–60 FPS;
- spectrogram render samples of 59–60 FPS;
- 480–488 received rows/s in 60–61 batches/s;
- spectrum render time approximately 0.02–0.17 ms in sampled seconds;
- spectrogram upload approximately 0–0.08 ms and draw approximately 0–0.10 ms;
- zero replaced waterfall batches and rows;
- zero stale or malformed messages;
- 72 correct circular-texture wraps;
- aggregate Firefox multiprocess RSS warming from 971.7 MiB to a 984–1,003 MiB cache/GC plateau, including observed GC reductions rather than monotonic growth.

After warm-up at index 0, process sampling reported approximately 31.5% CPU for the Firefox parent and 10.8% for the analyzer content process (about 42% of one CPU core combined). The managed backend used approximately 34% of one core during the same sample. These are host/process samples rather than normalized whole-machine percentages.

All eight hardware steps were also applied in the live GPU browser. Returned point counts were 26, 52, 104, 208, 416, 832, 1,664, and 3,328; sampled spectrum and spectrogram rates were approximately 58–63 FPS, waterfall rates matched 480/240/120/60 rows/s, and no stale or malformed generation rendered.

The vertical shader max-sampled 2,400 visible source rows over a 442-pixel canvas at the fastest profile, approximately 5.43 source rows per output pixel. Explicit zero-initialization prevents Firefox's lazy texture-clear stall after point-count changes. A deterministic simulator test remains the controlled short-hop proof; no synchronized RF burst generator was available, so ambient RF was not presented as controlled evidence.

GPU utilization percentage could not be collected because `intel_gpu_top` or an equivalent utilization counter is unavailable on this host. Hardware acceleration and renderer identity were verified through the WebGL debug renderer interface.

## Hardware lifecycle

The opt-in lifecycle test applied every profile, validated a v4 temporal frame at each point, restored Auto RBW, stopped acquisition, closed the device, and immediately reopened it successfully. A separate managed-service run also restored Auto before shutdown. Both backend and frontend services were left stopped.

Only one process may own the SAN-90. During initial validation a concurrently running managed backend caused the hardware test process to fail; stopping that existing owner resolved the issue. This is device contention, not a profile-table failure.

## Verification commands

```bash
python3 -m unittest discover -s tests -v
PATH="$HOME/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH" npm test -- --run
PATH="$HOME/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH" npm run lint
PATH="$HOME/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH" npm run build
SAN90_HARDWARE_TESTS=1 python3 -m unittest tests.hardware.test_san90_resolution_tradeoff -v
python3 backend/tools/test_san90_eight_profiles.py --duration 2
python3 backend/tools/test_san90_stability.py --duration 600 --step-index 0 --transition-cycles 0
```

GPU-backed browser validation used Firefox 130 through geckodriver on the physical display. The browser test is intentionally not part of the default automated suite because it requires a logged-in graphical session and exclusive SAN-90 ownership.

POI remains nullable: no exact SDK POI field or verified formula has been identified. It is not inferred from trace rate, row duration, or display FPS. VBW, AGC, sweep-time, and hardware-span controls were deliberately left unchanged.
