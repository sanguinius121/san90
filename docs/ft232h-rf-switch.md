# FT232H external RF switch

## Architecture

The RF switch is a low-rate management subsystem beside `AnalyzerService`. It never runs in the SAN-90 owner thread, trace polling loop, WebSocket spectrum publisher, waterfall batching path, or WebGL renderer.

`RfSwitchManager` owns one persistent switch connection, serializes operations, and runs an independent low-rate reconnect worker. The worker checks the connected GPIO state or retries USB connection every two seconds. It never runs in or blocks analyzer acquisition. The transport-neutral `RfSwitch` interface has FT232H and simulator implementations. The UI uses low-rate REST status polling and keeps connection state separate from requested and GPIO-reported paths.

Before every connection attempt, the FT232H driver flushes PyFtdi's USB enumeration cache. PyFtdi requires this after physical unplug/replug because the device may return at a new USB address; retaining the old object otherwise produces repeated USB error 19 failures.

The selection policy is session-only and manual. Every backend session and successful automatic reconnect initializes and verifies RF8. A disconnect discards any RF1–RF7 request, and reconnect never silently restores it. Backend shutdown attempts and verifies RF8 before closing the FT232H. Frequency and RBW settings have no connection to RF-path selection.

The RF-switch board is powered by the FT232H 3.3 V output. A physical USB disconnect therefore reports both ports as unknown, because the switch may be unpowered. If USB remains powered but PyFtdi releases or loses its controller, RF8 is shown only as the expected pull-up fail-safe and remains unverified until GPIO communication succeeds.

## Configuration

Hardware mode:

```bash
export SAN90_RF_SWITCH_ENABLED=true
export SAN90_RF_SWITCH_BACKEND=ft232h
export SAN90_RF_SWITCH_URL=ftdi://ftdi:232h/1
export SAN90_RF_SWITCH_DEFAULT_PATH=rf8
npm run backend:start
```

The managed backend now enables the physical FT232H backend by default, so
the exports above are needed only to override the URL or make the selection
explicit. To intentionally disable RF-switch support:

```bash
export SAN90_RF_SWITCH_ENABLED=false
npm run backend:start
```

Development simulator:

```bash
export SAN90_RF_SWITCH_ENABLED=true
export SAN90_RF_SWITCH_BACKEND=simulator
npm run backend:start:simulator
```

RF switch support defaults to enabled with the FT232H backend. If the device
is absent, SAN-90 acquisition continues while the independent reconnect worker
waits for it. It never silently falls back from FT232H to the simulator.
`SAN90_RF_SWITCH_SETTLE_MS` may override the default 5 ms settling delay and
must represent 0–100 ms. `SAN90_RF_SWITCH_RECONNECT_SECONDS` controls the
independent reconnect interval and defaults to 2 seconds.

## Linux dependency and permissions

Install the Python dependency into the same environment used by the backend:

```bash
python3 -m pip install -r backend/requirements.txt
```

PyFtdi uses PyUSB/libusb. On Debian or Ubuntu:

```bash
sudo apt-get install libusb-1.0-0
sudo groupadd -f plugdev
sudo usermod -aG plugdev "$USER"
```

Create `/etc/udev/rules.d/70-san90-ft232h.rules`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0403", ATTR{idProduct}=="6014", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

Then reload the rules, reconnect the FT232H, and start a new login session if group membership changed:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Only one process may claim the FT232H. Close any other PyFtdi/libusb test utility before starting the backend.

## API

- `GET /api/rf-switch/capabilities`
- `GET /api/rf-switch/status`
- `PUT /api/rf-switch/path` with `{"path":"rf1"}` through `{"path":"rf8"}`

A path-change response is successful only after GPIO readback matches the request.

Status exposes `connection_state`, `hardware_present`, nullable requested/reported ports, GPIO value, verification state, reconnect attempts, and connection/disconnection timestamps. A path request while unavailable is rejected without queueing:

```json
{"detail":{"code":"rf_switch_unavailable","message":"The FT232H RF switch is not connected."}}
```

## Automated tests

```bash
python3 -m unittest tests.test_rf_switch
npm test -- --run src/components/controls/RfPathControl.test.tsx
```

## Hardware integration test

Run from the repository root:

```bash
python3 backend/tools/test_ft232h_rf_switch.py status
python3 backend/tools/test_ft232h_rf_switch.py set rf1
python3 backend/tools/test_ft232h_rf_switch.py set rf2
python3 backend/tools/test_ft232h_rf_switch.py set rf7
python3 backend/tools/test_ft232h_rf_switch.py set rf8
python3 backend/tools/test_ft232h_rf_switch.py cycle
```

Each invocation leaves the hardware at RF8 before exit. In particular, `cycle` verifies RF2 as `AD6:AD5:AD4 = 001` and the full sequential mapping through RF8 `111`.

## Manual validation checklist

- Start without the FT232H: SAN-90 acquisition remains usable, the selector is disabled, and the reconnect counter advances.
- Connect the FT232H without restarting the backend: it automatically initializes and verifies RF8, then enables the selector.
- Start with the FT232H: startup selects and verifies RF8.
- Select RF1 through RF8 and measure `000` through `111`; for RF2, AD4 is high and AD5/AD6 are low.
- Verify RF1 alone shows the external-LNA badge after successful readback.
- Change center frequency and all RBW profiles; the selected RF path remains unchanged.
- Restart only the frontend; the backend-selected RF path remains unchanged.
- Restart the backend; RF8 is selected rather than restoring a non-default path.
- Stop the backend; RF8 is written and the FT232H USB controller is released.
- Disconnect the FT232H while RF1–RF7 is selected; acquisition continues, requested/reported ports become unknown, and the UI explains that both FT232H and externally powered switch are disconnected.
- Reconnect without restarting the backend; automatic recovery initializes and verifies RF8 and requires a new manual RF1–RF7 selection.
- Stop the backend while reconnecting; the reconnect worker exits promptly without leaving an open controller.

## Assumptions

- AD4, AD5, and AD6 are wired as the three address bits with AD4 as the least-significant bit.
- While the FT232H remains USB-powered, hardware pull-ups are expected to select address `111` / RF8 whenever PyFtdi releases its pins. This state is unverified without readback.
- When the FT232H is physically disconnected, its 3.3 V output and the RF-switch board are unpowered; no physical RF path is assumed.
- GPIO input readback represents the actual driven address pins, not internal RF-switch contact detection.
- RF1 external gain calibration and automatic power correction are outside this implementation.
