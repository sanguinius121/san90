# SAN-90 batched waterfall — Subphase B

Date: 2026-07-19  
Hardware: SAN-90, API 0.55.88, MCU/FPGA 0.55.103

## Result

Subphase B passes the hardware acquisition, batching, protocol, browser, stability, restoration, and immediate-reopen checks. The simulator and version-2 spectrum path remain intact. The complete captured measurements are in [san90-waterfall-subphase-b-metrics.json](san90-waterfall-subphase-b-metrics.json).

| Measurement | Safe auto-RBW | Fast manual request 300 kHz | 10-minute fast run |
|---|---:|---:|---:|
| Actual RBW | 60,306.091 Hz | 241,224.365 Hz | 241,224.365 Hz |
| Points / FFT | 3,328 / 4,096 | 832 / 1,024 | 832 / 1,024 |
| Actual span | 101.5625 MHz | 101.5625 MHz | 101.5625 MHz |
| SDK traces/s | 7,625.89 | 30,520.55 | 30,519.83 |
| Effective point rate | 25.379 Mpoint/s | 25.393 Mpoint/s | 25.393 Mpoint/s |
| Spectrum snapshots/s | 59.994 | 60.032 | 60.000 |
| Waterfall rows/s | 59.794 | 239.993 | 240.000 |
| Batches/s | 59.794 | 59.998 | 60.000 |
| Rows/batch | 1 | 4 | 4 |
| Mean traces/row | 127.157 | 127.173 | 127.166 |
| Mean/max deadline jitter | 73.40 / 662.04 µs | 18.72 / 600.84 µs | 19.45 / 1,996.38 µs |
| Mean max-update cost | 1,281.58 ns/trace | 409.29 ns/trace | 406.56 ns/trace |
| Mean row/batch finalization | 36.21 / 24.14 µs | 15.82 / 26.29 µs | 15.21 / 24.97 µs |
| Estimated protocol wire rate | 1.011 MB/s | 0.412 MB/s | 0.412 MB/s |
| Python process CPU | 31.47% of one core | 31.61% | 31.19% |
| Maximum RSS | 91.96 MiB | 91.96 MiB | 91.96 MiB |

The 600-second run produced 151,200 rows and 37,800 complete batches. It recorded zero timeouts, invalid packets, acquisition errors, malformed batches, missed deadlines, empty rows, replaced batches, or replaced rows. Reported RSS growth was 0.0 MiB.

After the stability run, auto RBW restored 3,328 points at 7,629.65 traces/s and 59.994 rows/s. Closing and immediately reopening the SAN-90 then produced 3,328-point safe-profile data at 7,617.86 traces/s.

## Owner-thread integration

`San90Source` remains the sole owner of all SDK calls. Each successful `RTA_GetRealTimeSpectrum_Raw` result is exposed as one contiguous `PacketFrame × FrameWidth` uint8 NumPy view. The existing latest trace is copied for the independently scheduled 60 FPS float32 spectrum snapshot. The same native packet is passed to `TimedWaterfallBatchProducer.add_packet` without per-trace float conversion or per-point Python iteration.

The producer reconstructs monotonic trace positions across the SDK packet and splits only where a row deadline falls. Each packet segment is reduced with one vectorized `np.max(..., axis=0)` and merged into the reusable active-row uint8 accumulator with `np.maximum`. Every native trace contributes to exactly one non-empty row.

`TraceTimestampStep` is a system-timer count, not seconds: this unit reports `16384`, while `TimeResolution` is 32 ns. Directly multiplying it by 1e9 caused the initial smoke test to stall. Row segmentation therefore derives per-trace monotonic spacing from the explicitly second-valued `PacketAcqTime / PacketFrame`, which also agrees with the measured native trace rate. Device and host timestamps on completed rows retain the latest relevant trace time; the producer also retains the first and last monotonic receipt positions internally.

The first deadline is `first_trace_monotonic + row_period`. Subsequent deadlines advance with `next_deadline += row_period`; they never reset from the current time. A crossed non-empty interval is finalized once. If scheduling crosses further intervals, no empty display rows are fabricated; the missed and empty-period metrics increment instead. No such miss occurred in the hardware runs.

## Profile and generation behavior

Defaults are chosen from actual SDK output after `RTA_Configuration`, not the requested RBW:

- actual RBW at least 200 kHz and fewer than 2,000 points: 240 rows/s, 60 batches/s, four rows/batch;
- otherwise: 60 rows/s, 60 batches/s, one row/batch.

`SAN90_WATERFALL_ROWS_PER_SECOND` (or the legacy `SAN90_WATERFALL_FPS`), `SAN90_WATERFALL_BATCHES_PER_SECOND`, and `SAN90_WATERFALL_ROWS_PER_BATCH` remain available as consistent operator overrides. The service manager no longer forces the legacy 60-row override, allowing hardware profile selection to work by default.

All reconfiguration is serialized on the SDK owner thread. A successful transaction stops acquisition, discards partial old-generation row and batch data, resizes producer buffers, increments the generation, resets deadlines, restarts, and confirms a valid new-generation frame. The short hardware sequence observed only generation 2 during fast mode and generation 3 after returning to safe mode. No batch mixed 3,328- and 832-point data.

## Bounded exchange and service

Only complete `WaterfallBatch` objects enter the one-slot newest-batch exchange. Publishing takes a lock only long enough to replace the slot; the owner thread never waits for FastAPI or WebSocket clients. Slow readers can replace a whole old batch, with both replaced batches and rows counted. No unbounded queue was introduced.

FastAPI drains real SAN-90 batches into the existing protocol-v3 `0x03` publisher. Version-2 spectrum and status frames are unchanged. Actual sent bytes are now classified as spectrum or waterfall bytes. At 832 points, measured protocol traffic was approximately 206.9 kB/s waterfall plus 205.5 kB/s spectrum, or 412.4 kB/s total including headers.

## Chromium and FHSS observations

Chromium was run against `/?source=san90` using the existing Subphase A frontend. The fast-profile capture showed 832 FFT points, approximately 30,514 SDK traces/s, 61 displayed spectrum FPS, 248 received waterfall rows/s, 62 batches/s over the one-second UI sample, zero replaced snapshots, and zero invalid frames. The plot reported an 8.53-second history and was captured after more than one 2,048-row texture wrap, with no visible row reversal or corruption. Generation and point-count changes cleared the old texture.

- [Fast-profile Chromium capture](san90-fast-profile.png)
- [Safe-profile Chromium capture](san90-safe-profile.png)

With the same live RF environment and display scale, the 240-row capture visibly separated short horizontal emissions into more individual time slices, while the 60-row capture merged more activity into fewer rows. The higher rate shortened visible history from 34.13 seconds to 8.53 seconds. Noise brightness did not visibly increase enough to obscure the emissions. This is a practical visual observation, not a controlled RF experiment: the ambient signal was not generated by a synchronized test source, and changing the verified hardware profile also changes RBW and point count. A controlled FHSS generator is still needed for a quantitative hop/dwell comparison.

The headless Chromium process was transient, so a reliable browser CPU percentage was not captured. Backend wire metrics, renderer FPS, received row/batch rates, invalid/stale counters, history, and post-wrap texture output were captured. No stale or malformed batch was reported.

## Files

Created:

- `backend/tools/test_san90_waterfall_batches.py`
- `tests/hardware/test_san90_waterfall_batches.py`
- `docs/san90-waterfall-subphase-b-metrics.json`
- `docs/san90-fast-profile.png`
- `docs/san90-safe-profile.png`
- this report

Modified:

- `backend/analyzer/waterfall.py`
- `backend/analyzer/raw_buffers.py`
- `backend/analyzer/san90.py`
- `backend/api/service.py`
- `backend/main.py`
- `scripts/manage-services.sh`
- `tests/test_waterfall_batches.py`

## Verification and reproduction

Software checks:

```bash
python3 -m unittest discover -s tests -v
export PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH
npm test -- --run
npm run lint
npm run build
```

Short opt-in hardware regression:

```bash
SAN90_HARDWARE_TESTS=1 python3 -m unittest tests.hardware.test_san90_waterfall_batches -v
```

Full safe/30-second-fast/10-minute-fast/restore/reopen validation:

```bash
python3 backend/tools/test_san90_waterfall_batches.py \
  --safe-duration 5 \
  --fast-duration 30 \
  --stability-duration 600 \
  --report-interval 30 \
  --json-output docs/san90-waterfall-subphase-b-metrics.json
```

Browser validation:

```bash
NODE_BIN_DIR=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin ./scripts/manage-services.sh start backend san90
NODE_BIN_DIR=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin ./scripts/manage-services.sh start frontend
# Open http://localhost:5173/?source=san90 in Chromium.
```

Both managed services were stopped after validation, and the device was left in the safe auto-RBW profile.

## Unresolved items

- A synchronized FHSS source is needed to quantify dwell separation rather than assess it visually.
- Browser CPU needs a persistent browser profiling harness if it is required as a numeric acceptance gate.
- The SDK header does not document the conversion of `TraceTimestampStep` system-timer counts to per-output-trace seconds. `PacketAcqTime / PacketFrame` is used because its documented unit and measured rates agree; this should be confirmed with HAROGIC if absolute per-trace device timestamp accuracy becomes necessary.
