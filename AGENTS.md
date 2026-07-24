# SAN-90 repository instructions

## Project overview

This repository implements a real-time browser spectrum analyzer for the
HAROGIC SAN-90. It includes:

- a FastAPI backend and versioned binary WebSocket service;
- a Python `ctypes` binding to the vendored HTRA Linux SDK;
- a single-owner-thread SAN-90 RTA acquisition path;
- a source-compatible NumPy simulator;
- bounded temporal-spectrum and max-hold waterfall aggregation;
- a React/TypeScript/Vite frontend using Zustand;
- a Web Worker binary parser, WebGL2 plot renderers, and Canvas 2D overlays;
- an optional PyFtdi FT232H eight-path RF switch;
- a bounded 640×640 GRAY8 ZeroMQ image stream for an external AI detector.

Primary entry points:

- Backend application: `backend/main.py`
- Analyzer lifecycle and WebSocket pump: `backend/api/service.py`
- SAN-90 source: `backend/analyzer/san90.py`
- Simulator: `backend/analyzer/simulator.py`
- Frontend: `src/main.tsx`, `src/App.tsx`, and `src/components/AppLayout.tsx`
- Browser WebSocket path: `src/data/WebSocketSpectrumSource.ts`
- Worker parser: `src/workers/frameParser.worker.ts`
- Spectrum/waterfall renderers: `src/rendering/SpectrumRenderer.ts` and
  `src/rendering/SpectrogramRenderer.ts`

The vendor SDK is under `harogic/`. Treat its headers, examples, and libraries
as authoritative for SDK symbols and ABI details; never invent a function,
enum, field, or return-code meaning.

## Required startup procedure

At the start of every new Codex session:

1. Read this file completely.
2. Read `docs/project-status.md` when it exists.
3. Run `git status --short` and preserve all existing user changes.
4. Run `git branch --show-current` and inspect recent history with
   `git log --oneline --decorate -20`.
5. Identify nested-repository, untracked, generated, and runtime files before
   editing.
6. Read the implementation, tests, and relevant current documentation for the
   requested area.
7. Inspect all call sites before changing shared models or protocols.
8. Limit edits to the requested scope. Do not reformat or refactor unrelated
   files.

Check service state before assuming a frontend network error is an application
bug:

```bash
npm run services:status
tail -n 100 .run/backend.log
tail -n 100 .run/frontend.log
```

The nested path `AI services/AI-for-san90` is a Git link and may contain user
runtime changes. The main repository currently lacks `.gitmodules`; do not
delete, reset, initialize, or replace this directory without first resolving
its provenance and preserving local work.

## Source-of-truth hierarchy

Use this order when evidence conflicts:

1. Current source code and tests.
2. Actual hardware readback and current measured validation reports.
3. Current project documentation, especially `docs/project-status.md`,
   `docs/realtime-binary-protocol.md`, and measured hardware reports.
4. Git history.
5. Comments, old milestone prompts, and assumptions.

Historical phase reports are evidence for the phase they describe, not
necessarily current behavior. Correct documentation when meaningful completed
work makes it inaccurate. Report uncertainty rather than upgrading simulator
or historical evidence to current hardware verification.

## Critical invariants

Preserve these current design constraints:

- Spectrum temporal publication is fixed at 60 frames/s. Each version-4 frame
  carries the newest trace and an interval maximum.
- Waterfall production is profile-driven at 60, 120, 240, or 480 rows/s and is
  normally transported in 60 batches/s with 1, 2, 4, or 8 rows per batch.
- The visible waterfall interval is 5.0 seconds. The 4,096-row circular texture
  is storage and does not define visible duration.
- Every native trace in a completed interval contributes to max-preserving
  temporal-spectrum and waterfall aggregation. Do not add trace skipping in
  those paths.
- Acquisition, producer exchanges, WebSocket client mailboxes, browser pending
  summaries, and AI queues are bounded. Prefer newest data and merge compatible
  maxima; never introduce an unbounded backlog.
- The SAN-90 SDK remains owned by one thread. FastAPI handlers serialize
  commands through it and never call one device handle concurrently.
- Hardware changes use the established safe transaction:
  stop, configure, read back actual values, rebuild generation-scoped buffers,
  restart, and wait for valid new-generation data.
- SDK readback is the applied-state source of truth. Requested UI drafts must
  not be presented as accepted hardware state.
- RTA native traces are contiguous `uint8`. Keep vectorized NumPy operations;
  do not create a Python object or loop iteration per point or native trace.
- `ScaleTodBm` and `OffsetTodBm` are configuration-generation data. Raw-to-dBm
  calibration and software amplitude offset must be applied exactly once to
  spectrum, waterfall normalization, statistics, and AI images.
- Spectrum and spectrogram share the frequency plot rectangle and mapping.
  Preserve alignment across resize and device-pixel-ratio changes.
- Simulator and SAN-90 implement the same application-facing source interface.
  New frontend behavior should be capability-driven rather than source-specific
  where practical.
- Binary protocol definitions, Python packing, TypeScript parsing, Web Worker
  transfer, tests, and documentation must stay synchronized.
- Device timestamps are not assumed to share the host epoch. Use host monotonic
  time for freshness, scheduling, and latches.
- Do not infer POI from trace rate, display FPS, or waterfall row time.

## Performance-sensitive code

Hot-path modules include:

- SDK acquisition and owner commands: `backend/analyzer/san90.py`
- Native mapping and snapshot exchange: `backend/analyzer/raw_buffers.py`
- Temporal spectrum aggregation: `backend/analyzer/spectrum_temporal.py`
- Waterfall aggregation/batching: `backend/analyzer/waterfall.py`
- WebSocket scheduling and bounded fan-out: `backend/api/service.py`
- Binary serializers: `backend/api/protocol.py`
- AI accumulation and publication: `backend/ai_stream/image_accumulator.py`,
  `backend/ai_stream/image_publisher.py`, and `backend/ai_stream/pipeline.py`
- Browser parsing/dispatch: `src/data/binaryProtocol.ts`,
  `src/workers/frameParser.worker.ts`, and
  `src/data/WebSocketSpectrumSource.ts`
- WebGL renderers: `src/rendering/SpectrumRenderer.ts` and
  `src/rendering/SpectrogramRenderer.ts`
- Imperative frame bus: `src/data/liveFrames.ts`

Changes in these files must avoid per-trace Python object churn, unnecessary
dtype changes, repeated full-array copies, blocking the acquisition thread,
unbounded queues, high-rate React/Zustand updates, avoidable browser-main-thread
work, and protocol drift. Reuse buffers and perform bulk array operations.
Measure before claiming a performance improvement.

## Hardware and simulator rules

- Simulator success is not SAN-90 verification. Label it explicitly as
  simulator-tested.
- Mocked PyFtdi tests are not FT232H hardware verification.
- SAN-90 controls, SDK status handling, USB lifecycle, acquisition rates,
  calibration, and profile transitions require exclusive real-device checks
  before being called hardware-validated.
- FT232H reconnect, GPIO readback, USB permissions, RF1–RF8 addressing, and
  fail-safe behavior require the physical FT232H/RF-switch assembly.
- Only one process may own the SAN-90 or FT232H. Fully exit SAStudio and other
  PyFtdi/libusb utilities before hardware tests.
- Keep SAN-90 acquisition operational when the optional RF switch is absent.
- FT232H reconnect must initialize and verify RF8; never restore RF1–RF7
  automatically after disconnect.
- Do not silently replace a missing physical RF-switch backend with its
  simulator.
- Hardware tests must restore the documented conservative SAN-90 profile,
  return the RF switch to RF8 where applicable, stop acquisition, close device
  handles, and verify immediate reopen when lifecycle behavior is in scope.
- Reference level is not an RF-input safety guarantee. Do not assume safe input
  limits without official device documentation.

Use `docs/project-status.md`, `docs/san90-control-mapping.md`,
`docs/san90-resolution-tradeoff-table.md`, and
`docs/ft232h-rf-switch.md` for current behavior and setup details.

## Protocol-change checklist

For any analyzer WebSocket change, update and validate all affected items:

1. Backend model and serializer in `backend/analyzer/models.py` and
   `backend/api/protocol.py`.
2. Protocol version, message type, header identity, and compatibility policy.
3. TypeScript parser in `src/data/binaryProtocol.ts`.
4. Web Worker and dispatch path.
5. Renderer or consumer logic.
6. Python and TypeScript protocol tests.
7. `docs/realtime-binary-protocol.md`.

Validate magic, version, header size, payload type and length, row count, point
count, array dtype, finite metadata, timestamps, configuration generation,
dynamic point counts, and stale-generation behavior.

For AI-image protocol changes, also update:

- `backend/ai_stream/protocol.py`;
- the ZeroMQ publisher and external consumer;
- `tools/ai_gray8_receiver.py`;
- `tests/test_ai_stream.py`;
- `docs/ai-gray8-protocol.md` and `docs/ai-gray8-stream.md`.

Preserve the exact 640×640 contiguous GRAY8 payload unless the protocol is
deliberately versioned and both sides gain compatibility handling.

## Testing commands

### Development-machine tests

Install dependencies first:

```bash
python3 -m pip install -r backend/requirements.txt
npm install
```

Run the Python suite; hardware modules remain skipped unless explicitly
enabled:

```bash
python3 -m unittest discover -s tests -v
```

Run frontend tests, lint, and the TypeScript/production build:

```bash
npm test
npm run lint
npm run build
```

For a TypeScript-only check:

```bash
npx tsc -b
```

Prefer focused modules during focused work, for example:

```bash
python3 -m unittest tests.test_protocol -v
npm test -- src/data/binaryProtocol.test.ts
```

Never report a command as passed unless it was run in the current task and its
result was inspected.

### Simulator smoke test

```bash
npm run backend:start:simulator
npm run frontend:start
npm run services:status
curl -s http://127.0.0.1:8000/api/analyzer/status
```

Open `http://localhost:5173/?source=simulator`, verify both plots and controls,
then cleanly stop:

```bash
npm run frontend:stop
npm run backend:stop
```

### SAN-90 tests

These require exclusive connected hardware and are opt-in:

```bash
SAN90_HARDWARE_TESTS=1 python3 -m unittest discover -s tests/hardware -v
```

Use narrower modules when only one subsystem changed. Hardware diagnostics are
under `backend/tools/`; inspect their arguments and cleanup behavior before
running them. Managed hardware operation is:

```bash
npm run backend:start
npm run frontend:start
npm run services:status
```

Managed SAN-90 start/stop may perform a guarded USB reset for SAStudio handoff.
Do not bypass or alter that lifecycle casually.

### FT232H tests

The mocked reconnect/mapping suite runs without hardware:

```bash
python3 -m unittest tests.test_rf_switch -v
npm test -- src/components/controls/RfPathControl.test.tsx
```

Physical validation uses:

```bash
python3 backend/tools/test_ft232h_rf_switch.py status
```

Read `docs/ft232h-rf-switch.md` before setting or cycling real paths.

### Browser/WebGL and AI validation

WebGL correctness and visual alignment require a real browser; unit/build
success alone does not verify GPU rendering, wrap continuity, DPI behavior, or
visual output. Use simulator first, then hardware only when required.

The synthetic AI benchmark is:

```bash
python3 backend/tools/benchmark_ai_stream.py --duration 60
```

The external YOLO service is separate and not managed by the repository service
script. Do not claim end-to-end AI operation from the backend publisher alone.

## Change discipline

- Preserve unrelated user changes, including dirty nested repositories.
- Never use destructive Git commands such as `git reset --hard` or discard
  files without explicit authorization.
- Do not force-push. Do not commit or push unless explicitly requested.
- Avoid broad refactors during focused bug fixes.
- Search for all producers, serializers, parsers, consumers, and tests before
  changing a shared model.
- Keep backward compatibility when practical and explicitly version wire
  incompatibilities.
- Update focused tests with behavior changes and run only the proportionate
  suite requested by the user.
- Keep new/replacement SDK archives, datasets, generated previews, model
  outputs/weights, build artifacts, logs, `.run/`, `.env` files, credentials,
  tokens, and private keys out of Git unless the user explicitly intends to
  version them. The existing vendored `harogic/` tree is intentional.
- Do not edit files under `harogic/` to make application code appear compatible.
- Use `apply_patch` for source and documentation edits.

## Documentation and project status

Meaningful completed work should update `docs/project-status.md` when it changes
architecture, supported features, API behavior, protocol formats, verified
hardware behavior, performance baselines, test coverage, limitations, or next
priorities.

Keep detailed measurements and historical tables in focused reports, not this
file. Status reporting must distinguish:

- implemented but untested;
- simulator-tested;
- automated-test verified;
- hardware-validated;
- planned or unresolved.

When documentation conflicts with verified current implementation, correct it
in scope or report the conflict and recommend a separate update.

## Required completion report

Every substantial task must finish with:

1. A concise implementation summary.
2. Files created and modified.
3. Important technical decisions and preserved invariants.
4. Commands and tests actually executed.
5. Exact observed results.
6. Hardware-validation status.
7. Known limitations, uncertainty, or risks.
8. Documentation updates.
9. The recommended next step.

Never report a test as passed unless it was actually run. Never report hardware
validation from simulator-only or mocked testing. Identify any test that could
not run and explain why.
