# SAN-90 RTA RBW, window, and detector mapping

Primary evidence is HTRA API 0.55.88 `harogic/Linux_API/htraapi/inc/htra_api.h`, the bundled RTA examples, and hardware readback from `RTA_Configuration`. All changes use the existing SDK-owner-thread stop/configure/restart transaction because the SDK does not document live RTA profile mutation as safe.

## RBW

| Application value | SDK field/value | Verified behavior |
|---|---|---|
| `auto` | `RTA_Profile_TypeDef.RBWMode = RBW_Auto` (`1`) | SDK chooses `RBW_Hz`; at the safe 101.5625 MHz span with Blackman–Nuttall it returned 60,306.09130859375 Hz. |
| `manual` plus positive `rbw_hz` | `RBWMode = RBW_Manual` (`0`), `RBW_Hz = requested double` | Numeric request is accepted and quantized to an available FFT configuration. No finite RTA-profile enum or device-specific min/max query exists. |

Official examples use manual RBW values in SWP mode, while the RTA structure independently documents the same RBW fields. Safe SAN-90 RTA measurements found that 15 kHz and 50 kHz requests both returned 60,306.091 Hz with 3,328 points/4,096 FFT; a 300 kHz request returned 241,224.365 Hz with 832 points/1,024 FFT. Span stayed 101.5625 MHz. Point count, FFT size, trace rate, and raw offset can change; buffers must be recreated. `ScaleTodBm` remained 0.5 dB/code in the measured configurations.

There is no application `rta_profile` setting because no corresponding SDK enum exists. The application exposes auto/manual numeric RBW and always returns the actual accepted value.

## Window

`RTA_Profile_TypeDef.Window` uses `Window_TypeDef`:

| Application name | SDK enum | Value | Measured actual RBW at auto mode |
|---|---|---:|---:|
| `flat-top` | `FlatTop` | 0 | 115,058.898926 Hz |
| `blackman-nuttall` | `Blackman_Nuttall` | 1 | 60,306.091309 Hz |
| `low-sidelobe` | `LowSideLobe` | 2 | 67,607.421875 Hz |
| `rectangular` | `Rect` | 3 | 30,517.578125 Hz |
| `kaiser` | `Kaiser` | 4 | 49,721.069336 Hz |

`Gaussian_CISPR` (`0x0a`) is excluded because the header says it is supported only in EMC mode. Every listed option was accepted and returned unchanged in continuous RTA raw mode. Window changes alter equivalent bandwidth/actual RBW and can affect amplitude correction, so actual RBW and the first new `ScaleTodBm`/`OffsetTodBm` are read atomically after restart. In the measured safe-span run, point count and span remained 3,328 and 101.5625 MHz.

## Detector

The application detector maps to `RTA_Profile_TypeDef.Detector`, whose type is `Detector_TypeDef` and whose header comment explicitly includes RTA. This is multi-frame detection before the raw RTA trace is returned. It is distinct from `TraceDetector`, which remained SDK-default positive-peak (`2`) with automatic trace-detect mode during the measurements.

| Application name | SDK enum | Value | Hardware readback |
|---|---|---:|---|
| `sample` | `Detector_Sample` | 0 | 0 |
| `positive-peak` | `Detector_PosPeak` | 1 | 1 |
| `average` | `Detector_Average` | 2 | 2 |
| `negative-peak` | `Detector_NegPeak` | 3 | 3 |
| `rms` | `Detector_RMS` | 6 | 6 |
| `auto-peak` | `Detector_AutoPeak` | 7 | coerced to 6 (`rms`) by this SAN-90/firmware configuration |

`Detector_MaxPower` and `Detector_RawFrames` are excluded because the header marks them SWP-only. Detector changes did not change RBW, point count, span, or trace rate materially in the measured configuration, but they still require the conservative RTA restart transaction and full actual-profile readback.

## Unresolved behavior

- The SDK provides no SAN-90-specific RBW range, step, or list of numeric values.
- Numeric RBW quantization boundaries are firmware/device policy and are not exhaustively enumerated.
- The reason `Detector_AutoPeak` is coerced to `Detector_RMS` is not documented; the UI must show the actual returned `rms` value.
- Live configuration safety is not documented, so all three controls require restart.
