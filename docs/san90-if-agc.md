# SAN-90 IF AGC controls

## SDK mapping

The authoritative declarations are in
`harogic/Linux_API/htraapi/inc/htra_api.h` from HTRA API 0.55.88:

- `RTA_Profile_TypeDef.EnableIFAGC` at line 1553 is `uint8_t`: `0` is off and
  `1` is on. `RTA_Configuration` returns the accepted value in `ProfileOut`.
- `Device_SetIFAGCTarget` at lines 2612–2613 takes an in/out `double *` in
  dBFS. The documented range is `-30..0 dBFS`.
- `Device_SetIFAGCPeriod` at lines 2615–2616 takes an in/out `double *` in
  seconds. The device behavior is one-shot for negative values, dynamic at
  zero, and periodic for positive values.
- `MeasAuxInfo_TypeDef.IFAGCGain` at line 1105 is runtime `double` state in
  dB. Positive values are amplification and negative values are attenuation.

There are no independent target or period getters. Consequently, enable is a
profile readback, target and period are verified-at-apply values returned
through the setter pointers, and gain is runtime-only acquisition auxiliary
state. The application samples gain at 10 Hz and reports it unavailable after
one second without a valid sample.

All three configurable values use the existing owner-thread
stop/configure/readback/start transaction. IF overflow remains a separate
monotonic latch and is not cleared by reconfiguration.

## UI behavior

The Amplitude panel contains an On/Off toggle, a `dBFS` target input, and a
mode-aware period control:

- One-shot sends `-1 s`.
- Dynamic sends `0 s`.
- Periodic reveals a positive seconds input.

Target and period are disabled while IF AGC is off. Gain is always read-only
and displays `—` until runtime auxiliary data is available. The frontend polls
the moderate-rate settings/status path every 500 ms; the acquisition path
continues to run at its native rate.

## Hardware verification

On 2026-07-28, SAN-90 model 67 with firmware 0.55.103 and HTRA API 0.55.88 was
tested at 2.45 GHz, 0 dBm reference level, automatic attenuation, preamplifier
off, and automatic RBW. Every SDK call returned status `0`.

| Case | Requested enable | Target dBFS | Period s | Returned enable | Returned target | Returned period | Gain samples | Stream resumed |
|---|---:|---:|---:|---:|---:|---:|---|---|
| Off | 0 | -9 | 0 | 0 | -9 | 0 | 0 dB | yes |
| Dynamic | 1 | -3 | 0 | 1 | -3 | 0 | 0 dB | yes |
| Dynamic | 1 | -9 | 0 | 1 | -9 | 0 | 0 dB | yes |
| Dynamic | 1 | -20 | 0 | 1 | -20 | 0 | 0 dB | yes |
| One-shot | 1 | -9 | -1 | 1 | -9 | -1 | 0 dB | yes |
| Periodic | 1 | -9 | 1 | 1 | -9 | 1 | 0 dB | yes |
| Periodic | 1 | -9 | 2 | 1 | -9 | 2 | 0 dB | yes |

Additional API checks showed exact acceptance of fractional `-9.5 dBFS` and
`0.25 s`, confirming that the native values are not integer-only. The UI uses
a conservative 1-unit button step while preserving typed fractional values.

The safe-input run produced no IF overflow and no AGC action, so runtime gain
movement, negative gain, and overflow mitigation near saturation are not yet
hardware-verified. No stronger RF signal was intentionally introduced.

Run the short standalone diagnostic only with exclusive device ownership:

```bash
python3 backend/tools/test_san90_if_agc.py --sample-seconds 0.6
```
