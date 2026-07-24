# Codex Implementation Prompt: Manual RF Path Selection Using FT232H in the SAN-90 Project

## Objective

Add support for an external 8-way RF switch controlled by an Adafruit FT232H board to the SAN-90 web spectrum analyzer project.

The switch uses three digital control bits to select one of eight RF input paths. The frontend must expose manual selection of all eight RF input ports. Two ports currently have known semantic roles:

- **RF1 — Dual-band LNA path:** an antenna and external LNA optimized for the 2.4 GHz and 5.8 GHz bands.
- **RF8 — Wideband antenna path:** the default general-purpose wideband antenna path.
- **RF2–RF7 — User-selectable auxiliary paths:** currently unassigned or reserved for future antennas, filters, LNAs, or other RF front-end modules.

All eight ports must remain selectable from the frontend. Unknown or unused ports should be labeled clearly as auxiliary/reserved rather than hidden.

The user must explicitly choose whether the LNA path is used. The software must **not automatically select RF1 based on center frequency, span, detected signal type, or any other acquisition setting**.

## Important Operating Principle

RF-path selection is a manual hardware control that is independent from SAN-90 frequency tuning.

For example, tuning the SAN-90 center frequency to 2.45 GHz or 5.8 GHz must not automatically enable the LNA path. The user may intentionally remain on the wideband antenna even while observing these bands.

The system may display a recommendation or warning in a future version, but it must not change the RF path without an explicit user command.

## Existing Hardware

The FT232H is connected to Linux through USB and is detected as:

```text
VID: 0403
PID: 6014
Device: FT232H Single HS USB-UART/FIFO IC
```

The external RF switch is powered from the FT232H board's 3.3 V supply and uses three control bits.

Use the FT232H `AD4`, `AD5`, and `AD6` pins as the switch address bits:

```text
FT232H AD4 -> RF switch A0 / least significant bit (LSB)
FT232H AD5 -> RF switch A1
FT232H AD6 -> RF switch A2 / most significant bit (MSB)
FT232H 3V  -> RF switch VCC
FT232H GND -> RF switch GND
```

Use `pyftdi.gpio.GpioAsyncController` for the AD bank. The selected control lines occupy bits 4, 5, and 6 of the low GPIO byte:

```python
AD4 = 1 << 4
AD5 = 1 << 5
AD6 = 1 << 6
CONTROL_MASK = AD4 | AD5 | AD6
```

## Switch Address Mapping

Assume the three address bits map sequentially to RF1 through RF8. The verified physical bit order is `AD6:AD5:AD4 = A2:A1:A0`, with `AD4` as the least significant bit. Therefore `001` selects RF2, `010` selects RF3, and so on:

| RF path | A2 | A1 | A0 | Address |
|---|---:|---:|---:|---:|
| RF1 | 0 | 0 | 0 | `000` |
| RF2 | 0 | 0 | 1 | `001` |
| RF3 | 0 | 1 | 0 | `010` |
| RF4 | 0 | 1 | 1 | `011` |
| RF5 | 1 | 0 | 0 | `100` |
| RF6 | 1 | 0 | 1 | `101` |
| RF7 | 1 | 1 | 0 | `110` |
| RF8 | 1 | 1 | 1 | `111` |

Assign stable identifiers to all eight paths, while retaining semantic labels for the two currently defined connections:

```text
RF1 = DUAL_BAND_LNA
RF2 = AUXILIARY_RF2
RF3 = AUXILIARY_RF3
RF4 = AUXILIARY_RF4
RF5 = AUXILIARY_RF5
RF6 = AUXILIARY_RF6
RF7 = AUXILIARY_RF7
RF8 = WIDEBAND_ANTENNA
```

The frontend must present RF1 through RF8 as normal manual choices. RF2–RF7 may initially use generic labels, but their identifiers and API values must remain stable so descriptive names can be added later without changing the electrical mapping.

## Fail-Safe Behavior

The hardware naturally pulls all three switch address lines HIGH when the FT232H controller is released or the controlling process exits.

Therefore:

```text
AD6:AD5:AD4 = 111 -> RF8 -> wideband antenna
```

This behavior is intentional and desirable.

RF8 must be treated as the hardware fail-safe and default path in the following situations:

- The SAN-90 application has not started.
- The RF-switch service has not initialized.
- The FT232H is disconnected.
- The FT232H controller is closed.
- The application exits normally.
- The backend crashes or loses ownership of the FT232H.
- No saved user preference is available.

Before intentionally releasing the FT232H, the software should attempt to write `111` and wait briefly before closing the device. However, failure to perform this final write must not be considered dangerous because the hardware returns to RF8 when released.

## Required User Experience

Add a manual eight-port RF path selector to the SAN-90 frontend.

Recommended UI:

```text
RF Input Path

[ RF1 — 2.4/5.8 GHz LNA ]
[ RF2 — Auxiliary ]
[ RF3 — Auxiliary ]
[ RF4 — Auxiliary ]
[ RF5 — Auxiliary ]
[ RF6 — Auxiliary ]
[ RF7 — Auxiliary ]
[ RF8 — Wideband antenna ]
```

A compact dropdown or segmented selector is also acceptable:

```text
RF Input Path: [ RF8 — Wideband antenna v ]
```

Available choices:

1. **RF1 — 2.4/5.8 GHz LNA**
   - Address `000`.
   - External LNA path.
   - Selected only by explicit user action.

2. **RF2 — Auxiliary**
   - Address `001`.
   - `AD4` is the LSB.

3. **RF3 — Auxiliary**
   - Address `010`.

4. **RF4 — Auxiliary**
   - Address `011`.

5. **RF5 — Auxiliary**
   - Address `100`.

6. **RF6 — Auxiliary**
   - Address `101`.

7. **RF7 — Auxiliary**
   - Address `110`.

8. **RF8 — Wideband antenna**
   - Address `111`.
   - Default and hardware fail-safe path.

The user must be able to select any port directly. Do not hide RF2–RF7 merely because their final RF front-end functions are not yet assigned.

The frontend must clearly show the requested port and the backend-reported hardware state.

Suggested status display:

```text
Requested port: RF3 — Auxiliary
Hardware state: RF3 (AD6:AD5:AD4 = 010)
FT232H: Connected
```

For RF1 and RF8, display their descriptive names. For RF2–RF7, display the generic auxiliary label until configuration metadata provides a better name.

If the requested state and GPIO readback do not match, display a visible warning rather than silently reporting success.

## Strict Manual-Control Requirement

Do not implement any of the following behaviors:

- Automatically select RF1 when the center frequency enters 2.4 GHz.
- Automatically select RF1 when the center frequency enters 5.8 GHz.
- Automatically select RF8 when the center frequency leaves those bands.
- Automatically select a path based on span.
- Automatically select a path based on SAN-90 RBW.
- Automatically select a path based on detected signal type.
- Automatically select a path based on YOLO or other AI inference results.
- Automatically change paths during a frequency sweep.

Frequency and RF-path controls must remain independent.

Changing the SAN-90 center frequency, span, RBW, window, detector, attenuation, preamplifier, reference level, or gain strategy must not modify the RF switch state.

## Backend Architecture

Implement the RF switch as an isolated hardware service or manager owned by the backend.

Suggested components:

```text
backend/
  hardware/
    rf_switch/
      __init__.py
      base.py
      ft232h_switch.py
      simulator.py
      models.py
```

Suggested responsibilities:

### `base.py`

Define a hardware-independent interface:

```python
class RfSwitch:
    def open(self) -> None: ...
    def close(self) -> None: ...
    def set_path(self, path: RfPath) -> RfSwitchStatus: ...
    def get_status(self) -> RfSwitchStatus: ...
```

### `models.py`

Define semantic enums and status models:

```python
from enum import Enum


class RfPath(str, Enum):
    RF1_DUAL_BAND_LNA = "rf1"
    RF2_AUXILIARY = "rf2"
    RF3_AUXILIARY = "rf3"
    RF4_AUXILIARY = "rf4"
    RF5_AUXILIARY = "rf5"
    RF6_AUXILIARY = "rf6"
    RF7_AUXILIARY = "rf7"
    RF8_WIDEBAND_ANTENNA = "rf8"
```

Suggested status fields:

```text
available
connected
requested_path
reported_path
raw_address
raw_gpio_value
readback_matches_request
last_error
updated_at_monotonic
```

### `ft232h_switch.py`

Implement the real FT232H device using PyFTDI.

Requirements:

- Use `GpioAsyncController`.
- Configure only AD4, AD5, and AD6 as outputs.
- Preserve unrelated GPIO bits where practical.
- Write all three switch bits in one logical operation.
- Read GPIO state after writes.
- Mask and decode only AD4–AD6.
- Verify the resulting address.
- Use a lock around device access.
- Do not allow multiple threads to issue overlapping FT232H commands.
- Do not repeatedly open and close the FT232H for each HTTP request.
- Keep one backend-owned connection open while the service is active.
- On shutdown, request RF8, then release the controller.

Suggested constants:

```python
FTDI_URL = "ftdi://ftdi:232h/1"

AD4 = 1 << 4
AD5 = 1 << 5
AD6 = 1 << 6
CONTROL_MASK = AD4 | AD5 | AD6

PATH_TO_ADDRESS = {
    RfPath.RF1_DUAL_BAND_LNA: 0b000,
    RfPath.RF2_AUXILIARY: 0b001,
    RfPath.RF3_AUXILIARY: 0b010,
    RfPath.RF4_AUXILIARY: 0b011,
    RfPath.RF5_AUXILIARY: 0b100,
    RfPath.RF6_AUXILIARY: 0b101,
    RfPath.RF7_AUXILIARY: 0b110,
    RfPath.RF8_WIDEBAND_ANTENNA: 0b111,
}
```

Convert a three-bit address to the AD-bank GPIO value:

```python
def address_to_gpio_value(address: int) -> int:
    if not 0 <= address <= 7:
        raise ValueError("RF switch address must be between 0 and 7")
    return address << 4
```

Decode readback:

```python
def gpio_value_to_address(value: int) -> int:
    return (value & CONTROL_MASK) >> 4
```

### `simulator.py`

Provide a simulator with the same API for development and automated tests when no FT232H is attached.

The simulator must support:

- Setting any of the eight RF ports.
- Reporting the current address.
- Injecting connection errors.
- Injecting readback mismatches.
- Starting in the wideband RF8 state.

## Device Discovery and Configuration

Support environment-based configuration:

```text
SAN90_RF_SWITCH_ENABLED=true
SAN90_RF_SWITCH_BACKEND=ft232h
SAN90_RF_SWITCH_URL=ftdi://ftdi:232h/1
SAN90_RF_SWITCH_DEFAULT_PATH=rf8
```

Development fallback:

```text
SAN90_RF_SWITCH_BACKEND=simulator
```

If RF switch support is disabled or no FT232H is found:

- SAN-90 spectrum acquisition must continue operating normally.
- The frontend must show the RF switch as unavailable.
- The backend must not crash or block SAN-90 startup.
- The wideband path should be assumed as the physical fail-safe state, but it must be clearly marked as unverified when GPIO readback is unavailable.

Do not silently switch to the simulator in production unless explicitly configured. A missing real device must be distinguishable from a simulated device.

## API Design

Add endpoints similar to:

```text
GET  /api/rf-switch/status
PUT  /api/rf-switch/path
```

Example request:

```json
{
  "path": "rf3"
}
```

Example successful response:

```json
{
  "available": true,
  "connected": true,
  "requested_path": "rf3",
  "reported_path": "rf3",
  "raw_address": 2,
  "raw_gpio_value": 32,
  "readback_matches_request": true,
  "last_error": null
}
```

Example wideband response:

```json
{
  "available": true,
  "connected": true,
  "requested_path": "rf8",
  "reported_path": "rf8",
  "raw_address": 7,
  "raw_gpio_value": 112,
  "readback_matches_request": true,
  "last_error": null
}
```

`112` is `0x70`, corresponding to AD6:AD5:AD4 = `111`.

Use an appropriate error status when:

- The FT232H is unavailable.
- The device is busy.
- USB permissions are missing.
- A write fails.
- GPIO readback does not match the requested address.

Do not report the requested path as successfully applied until GPIO readback has been checked.

## WebSocket or State Synchronization

Integrate RF-switch status into the existing application state without coupling it to the high-rate spectrum and waterfall data path.

Do not insert FT232H operations into:

- The SAN-90 acquisition owner thread.
- The native trace polling loop.
- The 60 FPS spectrum publication path.
- The waterfall batching path.
- The WebGL rendering loop.

RF-switch control is a low-rate management operation and must remain isolated from real-time acquisition.

The frontend may obtain state through:

- A dedicated low-rate WebSocket status message; or
- REST polling at a modest interval; or
- An immediate REST response plus an existing general status channel.

Do not send RF-switch status at spectrum frame rate.

## Persistence Behavior

The default physical and software path is wideband RF8.

For the first implementation, choose one of these explicit policies and document it:

### Preferred policy: session-only manual selection

- Start every backend session in wideband mode.
- Do not automatically restore any non-default port after a restart.
- Require the user to explicitly reselect RF1–RF7 when needed.

This is the safer and more transparent option.

### Optional future policy: remembered preference

A remembered user preference may be added later, but restoring any non-default RF port must be clearly visible and must not be inferred from frequency.

For this task, implement the preferred session-only policy unless the existing SAN-90 configuration framework already has an explicit user preference mechanism that makes the behavior obvious.

## Startup Sequence

Recommended backend startup sequence:

1. Start the SAN-90 backend normally.
2. Initialize the RF-switch manager independently.
3. Attempt to open the FT232H.
4. Configure AD4–AD6 as outputs.
5. Explicitly request RF8 / `111`.
6. Read back AD4–AD6.
7. Publish the resulting status.
8. Continue startup even if the RF switch is unavailable.

Do not automatically restore RF1 based on the SAN-90 center frequency.

## Path Change Sequence

When the user selects a path:

1. Validate the semantic path.
2. Convert it to the three-bit address.
3. Acquire the RF-switch device lock.
4. Write all address bits in one operation.
5. Wait for a short configurable settling interval, for example 1–10 ms.
6. Read back AD4–AD6.
7. Decode the reported address.
8. Compare requested and reported states.
9. Update backend status.
10. Return success only when the states match.

The settling delay must not block the SAN-90 acquisition thread.

## Frontend Safety and Clarity

When the user selects RF1, show a concise explanation such as:

```text
External 2.4/5.8 GHz LNA path selected. Monitor receiver overload when strong nearby signals are present.
```

Do not automatically change SAN-90 internal preamplifier, attenuation, gain strategy, or reference level when the external LNA is selected.

Those controls must remain independent because the user may have a specific measurement setup. A future optional workflow may offer recommended settings, but it must require confirmation.

For RF1, show a non-blocking informational badge:

```text
External LNA active
```

Do not label the LNA as active when only the requested state is known and GPIO readback failed.

## Shutdown Behavior

On normal backend shutdown:

1. Attempt to set the path to wideband RF8 / `111`.
2. Read back the result when possible.
3. Wait briefly for the switch to settle.
4. Close the FT232H controller.
5. Suppress shutdown-only hardware errors after logging them clearly.

The application must never delay shutdown indefinitely because of the FT232H.

## Logging

Add clear structured logs for:

```text
RF switch backend selected
FT232H device opened
FT232H device unavailable
RF path change requested
RF path changed successfully
RF switch readback mismatch
RF switch returned to wideband fail-safe
FT232H device closed
```

Include semantic path, RF channel, binary address, and raw GPIO value where useful.

Do not log repeatedly in a tight polling loop.

## Testing Requirements

### Unit tests

Test at least:

1. RF1 through RF8 map sequentially to addresses `000` through `111`.
2. RF2 maps to address `001`, confirming AD4 is the LSB.
3. Address `000` maps to GPIO value `0x00` for AD4–AD6.
4. Address `111` maps to GPIO value `0x70`.
5. Readback decoding uses only AD4–AD6.
6. Unrelated GPIO bits do not change the decoded address.
7. Invalid paths are rejected.
8. Invalid addresses are rejected.
9. Readback mismatch produces an error status.
10. Simulator supports all eight selectable ports and starts in RF8.
11. SAN-90 startup succeeds when the FT232H is absent.
12. Frequency changes do not modify RF path state.
13. RBW profile changes do not modify RF path state.
14. Restarting the backend returns the logical default to RF8.

### Hardware integration test

Provide a command-line test utility, for example:

```text
backend/tools/test_ft232h_rf_switch.py
```

Suggested commands:

```bash
python backend/tools/test_ft232h_rf_switch.py status
python backend/tools/test_ft232h_rf_switch.py set rf8
python backend/tools/test_ft232h_rf_switch.py set rf1
python backend/tools/test_ft232h_rf_switch.py set rf2
python backend/tools/test_ft232h_rf_switch.py set rf7
python backend/tools/test_ft232h_rf_switch.py cycle
```

The `cycle` command should:

1. Select each port RF1 through RF8 in sequence.
2. Verify addresses `000` through `111`.
3. Confirm specifically that RF2 produces `001`.
4. Return to RF8 and verify `111`.
5. Leave the hardware in RF8 before exiting.

Print both semantic and electrical states:

```text
Requested: rf1 — dual_band_lna
Reported RF channel: RF1
AD6:AD5:AD4: 000
Raw GPIO: 0x00
Verification: PASS
```

### Manual test checklist

- Start the backend with the switch unconnected; SAN-90 remains usable.
- Connect the FT232H and verify status changes to connected.
- Select RF1 and measure AD6:AD5:AD4 as `000`.
- Select RF2 and verify `001`, with AD4 HIGH and AD5/AD6 LOW.
- Select every remaining port and verify the complete binary sequence through RF8 = `111`.
- Change SAN-90 center frequency across multiple bands; RF path remains unchanged.
- Change RBW and acquisition profiles; RF path remains unchanged.
- Restart the frontend only; backend RF path remains unchanged.
- Restart the backend; system initializes RF8.
- Stop the backend; hardware returns to RF8.
- Disconnect the FT232H during operation; acquisition remains active and the UI shows a hardware error.
- Reconnect the FT232H; recovery must be explicit and predictable.

## Recovery Policy

If the FT232H disconnects while any non-default port RF1–RF7 is selected, the physical pull-up behavior should return the switch to RF8.

The backend must then:

- Mark the FT232H as disconnected.
- Mark the previously requested path separately from the currently verified path.
- Avoid claiming that the previously selected RF port remains active.
- On reconnection, initialize RF8 rather than silently reapplying RF1–RF7.
- Require the user to explicitly choose the desired port again.

This preserves the strict manual-selection requirement.

## Non-Goals

Do not implement these features in this task:

- Automatic frequency-based path selection.
- Automatic LNA gain control.
- Automatic SAN-90 attenuation changes.
- Automatic internal preamplifier changes.
- AI-based RF-path selection.
- Signal-strength-based path selection.
- Calibration compensation for external LNA gain.
- Automatic power correction in displayed dBm values.

The design should leave room for future calibration metadata, but the first implementation is only manual path control and reliable status reporting.

## Acceptance Criteria

The implementation is complete when:

1. The backend can control the external switch through FT232H AD4–AD6.
2. The frontend exposes direct manual selection of all eight ports RF1–RF8.
3. RF8 is the startup, shutdown, disconnect, and fail-safe path.
4. The LNA path is never selected automatically from frequency or acquisition settings.
5. GPIO readback is checked after each write.
6. Requested and reported paths are represented separately.
7. The RF-switch implementation cannot interrupt or reduce SAN-90 acquisition performance.
8. The application remains functional without FT232H hardware.
9. Simulator and hardware test utilities are provided.
10. Automated tests prove that frequency and RBW changes never modify the selected RF path.

## Final Instruction to Codex

Inspect the existing SAN-90 backend and frontend architecture before editing. Reuse the project's established configuration, API, state-management, logging, shutdown, simulator, and test patterns. Keep this feature modular and avoid refactoring unrelated acquisition or rendering code.

After implementation, provide:

1. A concise summary of the architecture.
2. A list of changed files.
3. The FT232H Linux dependency and udev setup instructions.
4. Commands for automated tests.
5. Commands for the hardware integration test.
6. A manual validation checklist.
7. Any assumptions made about the existing project structure.
