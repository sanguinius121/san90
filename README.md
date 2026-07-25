# Real-time Spectrum Console

A React/TypeScript RF analyzer interface with native WebGL2 plots, Canvas 2D measurement overlays, Zustand stores, a browser simulator, and a bounded binary WebSocket path for the SAN-90.

The independent external-AI GRAY8 waterfall publisher is documented in [docs/ai-gray8-stream.md](docs/ai-gray8-stream.md).

Manual external RF-path control through an Adafruit FT232H is documented in [docs/ft232h-rf-switch.md](docs/ft232h-rf-switch.md).

## Run

Requires a current Node.js LTS release.
For a complete fresh-machine setup, including Python, Node.js, the HAROGIC
udev/device configuration, and `usbreset`, see
[docs/dependency-installation.md](docs/dependency-installation.md).

```bash
npm install
npm run dev
```

### Background service commands

The project can start and stop each development service independently. Processes are placed in their own process group and recorded under `.run/`, so stop commands target only the matching project service.

```bash
# Real SAN-90 backend
npm run backend:start
npm run backend:stop

# Simulator backend
npm run backend:start:simulator
npm run backend:stop

# Vite frontend
npm run frontend:start
npm run frontend:stop

# Show both services
npm run services:status
```

Logs are written to `.run/backend.log` and `.run/frontend.log`. The frontend requires Node.js 20.19 or newer. If the active shell has an older Node version, activate a current version first or set `NODE_BIN_DIR` to its `bin` directory.

### Switching between the web backend and SAStudio

The SAN-90 firmware/USB session may not hand off cleanly between two different HTRA clients after an ordinary `Device_Close`. Managed SAN-90 backend start and stop therefore perform a guarded Linux USB reset for device `367f:0001`, which is the software equivalent of reconnecting the USB data interface. The reset refuses to run while either the backend or SAStudio4 is active.

Exit the application currently using the analyzer, then start the other one. A manual handoff reset is also available:

```bash
npm run backend:stop
npm run device:reset
# SAStudio can now be opened
```

When switching back, fully exit SAStudio before running `npm run backend:start`; backend start performs the reset automatically. Set `SAN90_USB_HANDOFF_RESET=0` only if automatic handoff reset is intentionally disabled.

For foreground operation, run the original backend or `npm run dev` commands in separate terminals and stop each one with `Ctrl+C`.

Simulator UI:

```text
http://localhost:5173/?source=simulator
```

SAN-90 UI (start the backend first):

```bash
python3 -m pip install --user -r backend/requirements.txt
ANALYZER_SOURCE=san90 \
SAN90_SPECTRUM_FPS=60 \
SAN90_WATERFALL_FPS=60 \
SAN90_STATUS_HZ=2 \
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```text
http://localhost:5173/?source=san90
```

The browser source selector changes the URL and reloads the matching frontend source. The backend source remains authoritative and is selected with `ANALYZER_SOURCE=simulator` or `ANALYZER_SOURCE=san90`. The SAN-90 WebSocket frames are parsed off the main thread before entering the same imperative rendering bus as the simulator.

Spectrum traces and interval-max waterfall rows default to 60 FPS. Override either independently with `SAN90_SPECTRUM_FPS` or `SAN90_WATERFALL_FPS` before starting the backend. The waterfall preserves the maximum native value observed between display rows, so short events are not discarded merely because the SDK trace rate is much higher than the browser rate. The yellow spectrum remains the latest trace at each display deadline, while blue persistence retains every delivered trace for a rolling one-second window. Sub-frame events are guaranteed only in the interval-max waterfall.

Simulator waterfall batching supports separate row and WebSocket rates. Without overrides it uses 60 rows/s in one-row batches and switches to 240 rows/s in four-row batches for the simulated fast RBW profile. Explicit settings must be consistent:

```bash
SAN90_WATERFALL_ROWS_PER_SECOND=240 \
SAN90_WATERFALL_BATCHES_PER_SECOND=60 \
SAN90_WATERFALL_ROWS_PER_BATCH=4 \
npm run backend:start:simulator
```

The equality `rows_per_second = batches_per_second × rows_per_batch` is validated at startup. `SAN90_WATERFALL_FPS` remains a legacy alias for the row rate. Subphase A does not change SAN-90 acquisition-side production; hardware continues sending legacy single-row messages until Subphase B is explicitly started.

## Backend checks

```bash
python3 -m unittest discover -s tests -v
npm test
npm run build
```

The SAN-90 control and lifecycle tests are opt-in because they open and retune the physical device. They restore the conservative 2.45 GHz, 0 dBm reference, automatic attenuation, preamplifier-off, low-noise configuration and verify immediate reopen:

```bash
SAN90_HARDWARE_TESTS=1 python3 -m unittest discover -s tests/hardware -v
```

Run the standalone SAN-90 RTA diagnostic independently of any web server:

```bash
python3 backend/tools/test_san90_acquisition.py \
  --center-hz 2450000000 \
  --span-hz 100000000 \
  --reference-level-dbm -10 \
  --duration 10 \
  --stats-interval 1 \
  --profile \
  --save-first-frame first_san90_frame.npz

python3 backend/tools/inspect_san90_frame.py first_san90_frame.npz
```

The hardware diagnostic loads the repository HTRA API 0.55.88 explicitly, opens only model code 67, forces the preamplifier off by default, reports actual accepted configuration, and closes the bus trigger and device in cleanup. Its reference level is not an RF input safety limit; confirm the attached signal is within the SAN-90 product specification before running it.

RTA has no direct span field. `--span-hz` records the requested display target and checks it against the actual start/stop frequencies returned by `RTA_Configuration`; the SDK's default N90 configuration currently returns 101.5625 MHz for a 100 MHz target.

## Binary frame protocol

The versioned little-endian protocol and its 96-byte version 2 header are specified in [docs/realtime-binary-protocol.md](docs/realtime-binary-protocol.md). Spectrum and waterfall are independent `0x01` float32 and `0x03` uint8 messages; runtime status is `0x10` JSON inside the binary envelope. Version 2 carries a configuration generation so the browser can discard stale traces after retuning or amplitude changes.

The hardware controls support center frequency, reference level, explicit automatic/manual attenuation, preamplifier mode, gain strategy, automatic/manual numeric RBW, RTA window, and RTA detector. RBW may be quantized by the hardware and may change the native point count, so the UI always displays the accepted value and rebuilds its plot resources on the new configuration generation. SDK mappings are documented in [docs/san90-control-mapping.md](docs/san90-control-mapping.md) and [docs/san90-rbw-window-detector-mapping.md](docs/san90-rbw-window-detector-mapping.md); measured profiles are recorded in [docs/san90-rta-profile-table.md](docs/san90-rta-profile-table.md).

To repeat the opt-in bandwidth/window/detector discovery while no backend owns the analyzer:

```bash
python3 backend/tools/list_san90_rta_profiles.py \
  --duration 0.5 --rbw-hz 15000 --rbw-hz 50000 --rbw-hz 300000 \
  --include-windows --include-detectors
```

VBW, IF AGC, sweep-time, and user-facing hardware span controls remain disabled for SAN-90 mode until separately verified.
