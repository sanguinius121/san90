# SAN-90 Spectrum Console — project status and handoff

Last updated: 2026-07-28

Repository: `/home/tuancoi/san90`  
Snapshot commit: `dc63492c9876708e5b726d8ed60d41197a0c61ab`

This document is the starting point for a new Codex session or a fresh
development machine. Runtime values below are a verified baseline, not a
guarantee of the device's current state. Query the status endpoints before
changing hardware.

## Project summary

The project is a browser-based real-time spectrum analyzer for the HAROGIC
SAN-90. It preserves a complete simulator path while supporting a real SAN-90,
an optional FT232H-controlled eight-way RF switch, and a separate AI image
stream.

The application is split into:

- React, TypeScript, Vite, Zustand, Lucide, WebGL2, Canvas 2D, and a Web Worker
  in the frontend.
- FastAPI, NumPy, ctypes, bounded buffers, and one SAN-90 owner/acquisition
  thread in the backend.
- The vendor HTRA Linux SDK vendored under `harogic/`.
- An optional external detector in `AI services/AI-for-san90`.

The main plots are not React charts. WebGL renders the spectrum and circular
waterfall textures, Canvas 2D renders axes and overlays, and live trace arrays
stay outside React state.

## Current milestone status

The following major features are implemented:

- Browser simulator and real SAN-90 use the same analyzer-source interface.
- SAN-90 discovery, open/configure/acquire/stop/close lifecycle.
- Raw RTA acquisition at the device's natural trace rate.
- Fixed 60 Hz temporal spectrum publication containing:
  - newest current trace;
  - interval maximum across all native traces since the previous publication.
- Adaptive max-hold waterfall production from 60 to 480 rows/s, sent as 60
  bounded binary batches/s.
- Eight hardware-measured manual-RBW resolution trade-off positions.
- A fixed five-second visible spectrogram span independent of texture depth.
- Circular waterfall wrapping, valid-row tracking, stale-generation rejection,
  and max-preserving vertical downsampling.
- Shared plot geometry so spectrum and spectrogram frequency axes align.
- Center frequency, reference level, attenuation, preamplifier, gain strategy,
  IF AGC, RBW, VBW, resolution trade-off, RTA window, and detector controls.
- Software amplitude offset applied exactly once to all dBm consumers.
- Recoverable IF-overflow warning.
- FT232H RF-path selection with fail-safe RF8 initialization and reconnect.
- Bounded 640×640 GRAY8 ZeroMQ image output for an external AI service.
- A bounded port-5558 AI-result subscriber and compact, frequency-aligned
  current-detection strip between the spectrogram and spectrum.
- A backend-owned Phase 1 frequency scan loops enabled center-frequency
  entries in order with verified-readback dwell timing and realtime status.
- Managed frontend/backend start and stop, including guarded SAN-90 USB reset
  for handoff to SAStudio.

The working UI was deliberately preserved through these milestones. Do not
replace the renderers or remove simulator mode during follow-on work.

## Verified hardware and SDK

- Device family: HAROGIC SAN-90, model code `67` (`SAN-90 N90 R0`).
- Device firmware: MCU `0.55.103`, FPGA `0.55.103`.
- HTRA API: exactly `0.55.88`.
- SAN-90 USB ID: `367f:0001`.
- Optional FT232H USB ID: `0403:6014`.
- Supported host architectures in the vendored SDK: `x86_64`, `aarch64`,
  and `armv7`.
- Native library:
  `harogic/Linux_API/htraapi/lib/<architecture>/libhtraapi.so.0.55.88`.

The ctypes layer intentionally validates the API version. Do not substitute an
older system `libhtraapi`; API `0.55.82` was already proven incompatible with
this firmware and caused `Device_Open` status `-49`.

The verified conservative startup profile is:

- center: 2.45 GHz;
- actual RTA span: approximately 101.5625 MHz;
- reference level: 0 dBm;
- attenuation: automatic;
- preamplifier: off;
- gain strategy: low-noise;
- RBW: automatic;
- VBW: 0.1 × RBW;
- window: Blackman–Nuttall;
- detector: positive peak.

Reference level is not an RF input safety limit. Confirm the signal level
against the product specification before attaching a source.

## Acquisition and rendering invariants

These are intentional design constraints and should not be weakened:

- Only the SAN-90 owner thread calls the SDK.
- FastAPI request handlers never call the SDK concurrently.
- Configuration uses the existing stop/configure/readback/restart transaction.
- Requested values and verified hardware values remain separate.
- Point-count and amplitude mappings belong to one configuration generation.
- Old-generation traces, rows, and incomplete batches are discarded.
- Native acquisition is never throttled to browser speed.
- There is no unbounded frame queue.
- The newest trace wins for the current spectrum.
- All intervening native traces contribute to interval maxima.
- The visible waterfall duration remains 5.0 seconds.
- The texture stores 4,096 rows but storage duration is not display duration.
- Device timestamps are preserved but are not trusted for freshness because
  the observed device epoch is not aligned with host Unix time. Host monotonic
  time drives age, deadlines, and latches.
- POI remains nullable. Do not derive it from trace rate, row duration, or FPS.

## Measured RBW trade-off table

Auto RBW is a separate mode. Manual slider index 0 prioritizes time resolution;
index 7 prioritizes frequency resolution.

| Index | Activation request | Actual RBW | Points | FFT | Measured native traces/s | Waterfall rows/s | Rows/batch | Visible rows |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 8 MHz | 7.719180 MHz | 26 | 32 | 979,040 | 480 | 8 | 2,400 |
| 1 | 4 MHz | 3.859590 MHz | 52 | 64 | 489,252 | 480 | 8 | 2,400 |
| 2 | 2 MHz | 1.929795 MHz | 104 | 128 | 244,764 | 480 | 8 | 2,400 |
| 3 | 1 MHz | 964.897 kHz | 208 | 256 | 122,382 | 480 | 8 | 2,400 |
| 4 | 500 kHz | 482.449 kHz | 416 | 512 | 61,191 | 480 | 8 | 2,400 |
| 5 | 300 kHz | 241.224 kHz | 832 | 1,024 | 30,595.5 | 240 | 4 | 1,200 |
| 6 | 150 kHz | 120.612 kHz | 1,664 | 2,048 | 15,297.5 | 120 | 2 | 600 |
| 7 | 50 kHz | 60.306 kHz | 3,328 | 4,096 | 7,647.5 | 60 | 1 | 300 |

Every profile uses a 60 FPS spectrum/render target and 60 waterfall batches/s.
The four widest profiles intentionally cap waterfall output at 480 rows/s
while still max-holding every native trace. See
`docs/san90-resolution-tradeoff-table.md` for coercions and measurement detail.

## Controls and special behavior

### Frequency and amplitude

- Center frequency keeps a local input draft while editing, so hardware polling
  cannot overwrite typing. It commits only on the existing explicit action.
- Its display unit defaults to GHz and can switch between GHz and MHz without
  changing the canonical Hz value or reconfiguring hardware. Validation and
  the backend request remain in Hz.
- The collapsible Frequency Scan control keeps independent entry drafts,
  initializes 400 MHz, 900 MHz, 2.44 GHz, 3.3 GHz, 5 GHz, and 5775 MHz with
  five-second dwell times and independent 10 MHz steps, supports GHz/MHz
  display units for both center and step, and disables manual center-frequency
  commits while the backend scan controller owns tuning.
- Frequency Scan entry configuration is stored as schema-versioned JSON at
  `config/frequency-scan.json` using same-directory temporary files, fsync, and
  atomic replacement. Entry order, stable IDs, enabled state, canonical Hz
  values, duration milliseconds, and unit preferences survive restart; scan
  runtime state is never persisted and startup is always idle.
- Scan-entry changes are accepted while scanning without interrupting the
  active dwell. The controller reads the latest configuration between entries;
  deleting or disabling every entry safely returns the loop to idle after the
  current dwell.
- The analyzer span remains hardware/readback-driven at approximately
  101.5625 MHz. The former user-adjustable Span sidebar section was removed so
  the fixed acquisition width remains consistent with AI image generation and
  detector frequency mapping.
- Spectrum and spectrogram WebGL resources remain mounted across scan
  center-frequency and configuration-generation changes. Verified frame
  bounds update the shared frequency axes in place, and spectrogram generation
  changes reset logical history without reallocating its texture. A
  21-transition SAN-90 run observed zero post-warm-up WebGL resource or texture
  allocations; the hardware publication gap remained approximately 131 ms.
- Reference-level `+` and `-` use a 10 dB step.
- The verified actual reference level drives the spectrum Y-axis maximum.
- Spectrum dynamic range is retained at 100 dB; current and temporal/max traces
  use the same scale.
- Manual attenuation is `3..33 dB` in 3 dB steps.
- SDK attenuation `-1` means automatic; a non-negative supported value means
  manual.
- Manual attenuation forces the preamplifier off.
- The actual attenuation readback comes from the hardware amplifier/attenuator
  state; the UI does not pretend a requested value was accepted.
- Amplitude offset is software-only, ranges from -100 to +100 dB in 1 dB
  increments, does not restart acquisition, and is included in status,
  waterfall mapping, spectrum values, statistics, and AI images.
- IF AGC enable uses `RTA_Profile_TypeDef.EnableIFAGC`; target and period use
  the SDK's in/out `double *` setters. The UI exposes One-shot (`-1 s`),
  Dynamic (`0 s`), and Periodic (positive seconds) without hiding the native
  values. Runtime gain comes from `MeasAuxInfo_TypeDef.IFAGCGain`, is sampled
  at 10 Hz, and is never user-settable.
- A short SAN-90 run on 2026-07-28 verified enable Off/On, targets `-3`, `-9`,
  `-20`, and `-9.5 dBFS`, and periods `-1`, `0`, `0.25`, `1`, and `2 s`
  without SDK errors or acquisition failure. All setter in/out values and
  profile enable readbacks matched exactly. Under the safe input condition,
  runtime gain remained `0 dB` and IF overflow remained false; gain movement
  and overflow mitigation near saturation remain unverified.
- VBW exposes only RBW and 0.1× RBW, defaulting to 0.1×. Manual, 0.01× RBW,
  and 10× RBW remain documented native SDK modes but are intentionally omitted
  from application capabilities and rejected by the web API.
- A short SAN-90 run on 2026-07-28 verified all five VBW modes under auto RBW
  and two manual RBW profiles. Ratio values tracked actual RBW exactly. Manual
  requests below actual RBW/1000 were raised to that floor, requests above
  200 MHz were capped at 200 MHz, and continuous values such as 12,345.67 Hz
  were preserved. Narrow VBW reduced native trace rate but did not alter point
  count or produce acquisition errors/timeouts.

### IF overflow

`APIRETVAL_WARNING_IFOverflow` (`-12`) is recoverable. The acquisition loop
continues to process a valid returned trace and does not disconnect or restart
the device. A monotonic 0.9-second latch exposes `if_overflow` through runtime
status; the frontend displays a red `IF OVERFLOW` warning while active.

There remains an SDK ambiguity: documentation does not explicitly guarantee
trace-buffer validity for every `-12` return, although verified behavior and
the API warning semantics support processing the supplied trace.

Simulator debug:

```bash
SIMULATOR_IF_OVERFLOW=true npm run backend:start:simulator
VITE_SIMULATOR_IF_OVERFLOW=true npm run frontend:start
```

### Sweep Time policy

Sweep Time is fixed to minimum (`Fast / auto`) and is not advertised by
capabilities or exposed through REST/UI controls. The separate Sweep section
was removed; Window function is now part of Bandwidth. Native mappings and
measured behavior remain documented for diagnostics in
`docs/san90-sweep-time.md`.

### Unsupported or deliberately deferred controls

User-facing hardware-span control remains disabled until its SDK behavior is
independently verified. Do not simulate successful hardware changes for
unsupported fields.

## FT232H RF switch

The managed backend now enables the physical FT232H RF-switch integration by
default. Set `SAN90_RF_SWITCH_ENABLED=false` to disable it explicitly.

- FT232H pins AD4, AD5, and AD6 select RF1 through RF8 (`000` through `111`).
- RF8 (`0x70` in the FT232H GPIO byte) is the only automatic startup/reconnect
  path.
- Startup and every reconnect write RF8, read it back, and require verification.
- A prior RF1–RF7 request is discarded after USB disconnect.
- When the FT232H is physically absent, requested/reported port and GPIO value
  are null, controls are disabled, and port changes return HTTP 503.
- SAN-90 acquisition continues while the RF switch is absent.
- A dedicated worker retries approximately every two seconds.
- The simulator is used only when
  `SAN90_RF_SWITCH_BACKEND=simulator` is explicitly selected.

The external RF switch is powered by the FT232H 3.3 V output. Therefore,
physical FT232H absence means the RF switch is also unpowered; RF8 must not be
reported as physically selected in that state.

See `docs/ft232h-rf-switch.md` for the udev rule and diagnostics.

## AI stream and detector status

The main backend contains a production-bounded AI image publisher:

- 640×640 single-channel GRAY8 images;
- absolute dBm normalization;
- target 7–10 images/s, default 10;
- ZeroMQ PUSH bound to `tcp://0.0.0.0:5557`;
- queue size 2, buffer pool size 4, drop-oldest behavior;
- normal operation does not block SAN-90 acquisition or WebSocket rendering.

Power profiles are selected with `AI_POWER_PROFILE` or
`PUT /api/ai-stream/power-profile`:

- `normal`: approximately -130 to -50 dBm;
- `external_lna`: approximately -120 to -20 dBm;
- `strong_signal`: approximately -100 to 0 dBm.

The external service at `AI services/AI-for-san90/yolo_detection.py`:

- connects a ZeroMQ PULL socket to port 5557;
- runs the selected YOLO weights or exported OpenVINO model;
- publishes detection JSON on `tcp://127.0.0.1:5558`;
- writes its latest JSON result under its runtime data directory.

Important limitations:

- The backend forwards current-frame per-detection frequency bounds through
  WebSocket type `0x11`; the browser holds annotations for 800 ms and does not
  consume the detector's accumulated `label_freq_ranges_hz` field.
- The detector's legacy frequency-label range history expands across tuning
  changes and remains unsuitable as a current detection result.
- OpenVINO on the verified Intel Arc integrated GPU sustained the 10 result/s
  input target with short latency; revalidate performance on other machines.
- The detector is not managed by `scripts/manage-services.sh`.
- Its requirements file pins older package versions than the manually installed
  environment previously used. Revalidate Torch/Torchvision/Ultralytics/OpenCV
  compatibility on the new machine.

### AI repository portability warning

`AI services/AI-for-san90` is recorded in the main repository as gitlink commit
`df4e9cf6b83ec6374728b2c1014b46ce05f23932`, but the main repository currently
has no `.gitmodules` file. A fresh clone may therefore contain only an
unpopulated gitlink and cannot automatically discover the nested repository
URL. Copy or clone the external AI repository into that exact path, check out
the recorded commit, or repair the submodule metadata before relying on it.

Generated `__pycache__/` and `data/` files can make the nested repository look
dirty; do not commit runtime artifacts.

## Binary and HTTP interfaces

### Ports

| Port | Purpose |
|---:|---|
| 5173 | Vite frontend |
| 8000 | FastAPI REST and `/ws/analyzer` |
| 5557 | Backend GRAY8 ZeroMQ PUSH stream |
| 5558 | External YOLO detection JSON PUB stream |

### Binary WebSocket

- Version 2: legacy current spectrum/status envelope.
- Version 3, type `0x03`: batched row-major uint8 waterfall.
- Version 4, type `0x02`: latest float32 trace plus interval-max float32 trace.
- Runtime status is type `0x10`.
- Current-frame AI frequency detections are version 2, type `0x11`.

All formats are little-endian and generation-aware. The browser Web Worker
validates magic, version, sizes, point counts, numeric metadata, and stale
generations. See `docs/realtime-binary-protocol.md`; do not change one side
without changing and testing the other.

### Main REST endpoints

```text
GET  /api/analyzer/source
GET  /api/analyzer/status
GET  /api/analyzer/capabilities
GET  /api/analyzer/settings
PUT  /api/analyzer/frequency
PUT  /api/analyzer/amplitude/reference-level
PUT  /api/analyzer/amplitude/offset
PUT  /api/analyzer/amplitude/attenuation
PUT  /api/analyzer/amplitude/preamplifier
PUT  /api/analyzer/amplitude/gain-strategy
PUT  /api/analyzer/bandwidth/rbw
PUT  /api/analyzer/resolution-tradeoff
PUT  /api/analyzer/sweep/window
PUT  /api/analyzer/detection/detector
POST /api/analyzer/start
POST /api/analyzer/stop
POST /api/analyzer/reconnect

GET  /api/rf-switch/capabilities
GET  /api/rf-switch/status
PUT  /api/rf-switch/path

GET  /api/ai-stream/status
GET  /api/ai-stream/preview.png
PUT  /api/ai-stream/enabled
PUT  /api/ai-stream/power-profile

WS   /ws/analyzer
```

Capabilities, verified readback, and error responses are authoritative; avoid
hardcoding SAN-90-only behavior in the frontend.

## Fresh-machine setup

### 1. Restore the repository

```bash
git clone <repository-url> san90
cd san90
git status --short
git log -1 --oneline
```

Confirm that the vendored HTRA headers and architecture-appropriate library
exist. Restore the external AI directory separately as described above if AI
work is required.

### 2. Install host prerequisites

Install Python 3, pip, libusb, `usbutils`, `usbreset`, and a Node.js version at
least 20.19. The service manager also accepts `NODE_BIN_DIR=/path/to/node/bin`.

```bash
python3 -m pip install --user -r backend/requirements.txt
npm install
```

For FT232H access, install the udev rule in `docs/ft232h-rf-switch.md` and make
the user a member of `plugdev`. Install the SAN-90 udev rule supplied at
`harogic/Linux_API/htraapi/configs/htra-cyusb.rules`. Re-log after changing
group membership.

For the external AI detector, install its requirements in a dedicated virtual
environment and verify Torch/Torchvision compatibility and CUDA availability
before starting it.

### 3. Smoke-test without hardware

```bash
npm run backend:start:simulator
npm run frontend:start
npm run services:status
```

Open `http://localhost:5173/?source=simulator`.

Stop the services with:

```bash
npm run frontend:stop
npm run backend:stop
```

### 4. Start real hardware

Fully exit SAStudio first, connect the SAN-90, and check USB discovery:

```bash
lsusb -d 367f:0001
lsusb -d 0403:6014
npm run backend:start
npm run frontend:start
```

Open `http://localhost:5173/?source=san90`.

Logs and process records are under `.run/`:

```bash
tail -f .run/backend.log
tail -f .run/frontend.log
npm run services:status
```

Managed SAN-90 start and stop perform a guarded USB reset because ordinary
`Device_Close` did not reliably hand the device to SAStudio. To switch clients:

```bash
npm run backend:stop
npm run device:reset
```

Then start SAStudio. Fully exit SAStudio before restarting the backend. Avoid
running both clients at once. Set `SAN90_USB_HANDOFF_RESET=0` only when the
automatic reset is intentionally unwanted.

## First checks in a new Codex session

Run read-only checks before editing or opening hardware:

```bash
pwd
git status --short
git log -1 --oneline
npm run services:status
lsusb | grep -E '367f:0001|0403:6014'
curl -s http://127.0.0.1:8000/api/analyzer/status
curl -s http://127.0.0.1:8000/api/rf-switch/status
curl -s http://127.0.0.1:8000/api/ai-stream/status
ss -lntp | grep -E ':5173|:8000|:5557|:5558'
```

Inspect `.run/backend.log` before interpreting a frontend `NetworkError`.
Usually it means port 8000 is not listening, backend startup failed, or the
browser is using the wrong source URL.

## Tests and diagnostics

Normal non-hardware checks:

```bash
python3 -m unittest discover -s tests -v
npm test
npm run build
npm run lint
```

The last recorded broad verification before this handoff was 62 Python tests
and 58 TypeScript tests, with lint and build passing. Later focused additions
also passed, including IF overflow, amplitude offset, manual attenuation, and
16 RF-switch tests. This is historical evidence; rerun relevant tests after a
fresh checkout.

Hardware tests are opt-in and exclusive:

```bash
SAN90_HARDWARE_TESTS=1 python3 -m unittest discover -s tests/hardware -v
```

Do not run them while SAStudio or another backend owns the analyzer.

Useful standalone tools:

```text
backend/tools/test_san90_acquisition.py
backend/tools/list_san90_rta_profiles.py
backend/tools/test_san90_eight_profiles.py
backend/tools/test_san90_attenuation.py
backend/tools/test_ft232h_rf_switch.py
```

Keep hardware checks short unless a stability or performance test was
explicitly requested. Restore the safe automatic-RBW profile and verify clean
close/reopen after intrusive tests.

## Repository status at handoff

The main source tree was at commit `dc63492` with no ordinary tracked source
changes. `git status` reported:

```text
 m "AI services/AI-for-san90"
```

That lowercase `m` is nested-repository dirtiness, primarily generated
bytecode/runtime data from running the detector. Treat it as user/runtime
state; inspect before cleaning and do not reset it destructively.

At the status capture, the SAN-90 backend and frontend were operational on the
original machine. The analyzer was connected and acquiring the automatic-RBW
profile near 7.63 ktraces/s, 60 spectrum FPS, and 60 waterfall rows/s. The
FT232H was physically absent and correctly in reconnecting/unavailable state.
The AI publisher was bound on port 5557 but had no consumer at that instant.
These observations are transient and should be re-queried.

## Known gaps and recommended next work

1. Make the external AI repository reproducible on a fresh clone by adding
   correct submodule metadata or vendoring it intentionally.
2. Add a managed AI-service command and explicit detector health reporting.
3. Remove or generation-scope the detector's legacy accumulated frequency
   ranges; the web strip already ignores them.
4. Keep hardware span deferred until SDK behavior is measured rather than
   guessed; preserve the verified Sweep Time readback path.
5. Revalidate FT232H reconnect on each target machine's USB permissions and
   udev configuration.

## Canonical documentation

- `docs/san90-sdk-analysis.md` — SDK discovery and binding decision.
- `docs/san90-acquisition-mode.md` — selected RTA acquisition workflow.
- `docs/san90-control-mapping.md` — verified control mappings.
- `docs/san90-if-agc.md` — IF AGC SDK mapping and short hardware acceptance.
- `docs/san90-vbw.md` — VBW enum mapping, coercion, and hardware measurements.
- `docs/san90-resolution-tradeoff-table.md` — measured eight-profile table.
- `docs/san90-resolution-tradeoff-report.md` — trade-off implementation report.
- `docs/realtime-binary-protocol.md` — browser streaming protocol.
- `docs/frequency-scan.md` — Phase 1 sequential scan API and scheduler behavior.
- `docs/spectrogram-continuity-alignment-report.md` — waterfall seam and axis
  alignment work.
- `docs/san90-raw-amplitude-format.md` — raw-code-to-dBm behavior.
- `docs/ft232h-rf-switch.md` — RF board wiring, configuration, and recovery.
- `docs/ai-gray8-stream.md` — backend AI image stream.
- `docs/ai-gray8-protocol.md` — GRAY8 wire protocol.
- `docs/ai-gray8-implementation-report.md` — AI publisher implementation.

When documents disagree, prefer current source code, hardware readback, and the
newer measured report. Do not invent SDK symbols or control semantics.
