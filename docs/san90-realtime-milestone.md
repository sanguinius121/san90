# SAN-90 real-time display milestone

## Result

The real SAN-90 RTA source now feeds the existing WebGL spectrum and spectrogram through a bounded FastAPI binary WebSocket pipeline. The browser simulator remains available with `?source=simulator`; `?source=san90` selects the WebSocket source. Analyzer setting controls remain intentionally disconnected for this milestone.

## Buffer and locking design

The SDK owner thread polls `RTA_GetRealTimeSpectrum_Raw` at the hardware rate. Each native packet is a caller-owned `uint8` array that the next SDK read overwrites. Before the next read, vectorized NumPy operations copy the packet's latest trace and per-bin packet maximum into fixed-size acquisition buffers. The interval maximum is accumulated in the raw domain.

At independent monotonic display deadlines (originally accepted at 25 Hz and now defaulting to 60 Hz), a two-slot exchange converts only the latest spectrum to contiguous float32 dBm and copies the interval max-hold row as uint8. The producer fills the non-published slot without a lock. A short lock protects only the slot/generation swap and copied consumption. The SDK read and conversion are never performed while holding this lock.

Each WebSocket client has a mailbox containing at most one unsent message of each type. A newer spectrum, waterfall, or status message replaces its older counterpart. Network backpressure therefore cannot grow a queue or reach the SDK thread.

## Amplitude conversion

The exact SDK mapping is:

```text
power_dBm = raw_uint8 * RTA_PlotInfo.ScaleTodBm + RTA_PlotInfo.OffsetTodBm
```

The verified scale is positive, so raw max-hold is equivalent to converting every trace and taking its dBm maximum. The running hardware configuration reported a scale of `0.5 dB/code` and an offset near `-113.0071 dBm`; these values remain SDK/configuration dependent. A mapping change resets the interval accumulator. See `san90-raw-amplitude-format.md`.

## Measured acceptance run

The table below records the original 25 FPS baseline. The current runtime default is 60 FPS for both publishers; this historical result remains useful as the pre-change performance baseline.

A continuous 605.04-second hardware/WebSocket run produced:

| Metric | Result |
|---|---:|
| Native point count | 3,328 |
| SDK acquisition rate | 7,629.13 traces/s |
| Effective point rate | 25.39 Mpoints/s |
| Spectrum WebSocket rate | 25.0002 frames/s |
| Waterfall WebSocket rate | 24.9985 rows/s |
| Runtime status rate | 2.00 updates/s |
| WebSocket traffic | 422,139 bytes/s |
| Process CPU | approximately 38–42% of one core |
| Native latest/max copy | approximately 0.0417 ms/packet |
| Display uint8-to-float32 conversion | approximately 0.0247 ms/snapshot |
| Snapshot creation | approximately 0.0358 ms/snapshot |
| RSS at 60 seconds | 95.1 MiB |
| RSS at 600 seconds | 95.6 MiB |
| Replaced display snapshots | 0 |
| Timeouts / invalid frames / errors | 0 / 0 / 0 |

Chromium inspection confirmed a live 3,328-bin spectrum and waterfall at approximately 25 FPS, actual 2.39921875–2.50078125 GHz axes, 101.5625 MHz span, and 60.306091 kHz RBW. REST stop, start, and reconnect all resumed the existing WebSocket stream. A separate lifecycle test closed and immediately reopened the device twice successfully.

## Test commands

```bash
python3 -m unittest discover -s tests -v
npm test
npm run lint
npm run build
```

Optional hardware lifecycle test:

```bash
SAN90_HARDWARE_TESTS=1 \
python3 -m unittest discover -s tests/hardware -p 'test_*.py' -v
```

Run the backend and UI:

```bash
ANALYZER_SOURCE=san90 \
SAN90_SPECTRUM_FPS=60 \
SAN90_WATERFALL_FPS=60 \
SAN90_STATUS_HZ=2 \
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

npm run dev
```

Open `http://localhost:5173/?source=san90`. Use `?source=simulator` for the browser simulator.

## Deferred work

- Device-setting controls are intentionally not wired to the SDK yet.
- The backend source is selected at process startup with `ANALYZER_SOURCE`; changing the browser selector does not mutate backend hardware ownership.
- Raw waterfall scale/offset are delivered in the 2 Hz runtime status rather than every waterfall header. A future control milestone should force an immediate status update when amplitude configuration changes.
