# SAN-90 RTA Sweep Time

This control is implemented from the HAROGIC SDK 0.55.88 header and a short
SAN-90 hardware validation on 2026-07-28.

## Native mapping and readback

`RTA_Profile_TypeDef.SweepTimeMode` is an `int`. The verified RTA values are:

| Application mode | SDK value | Meaning |
|---|---:|---|
| `minimum` | 0 | minimum sweep time |
| `minimum-x2` | 1 | 2 × minimum |
| `minimum-x4` | 2 | 4 × minimum |
| `minimum-x10` | 3 | 10 × minimum |
| `minimum-x20` | 4 | 20 × minimum |
| `minimum-x50` | 5 | 50 × minimum |
| `custom-multiple` | 6 | custom multiple |
| `manual` | 7 | manual target |

The SDK uses the shared `RTA_Profile_TypeDef.SweepTime` `double` as a
dimensionless multiplier in mode 6 and as seconds in mode 7. Fixed modes leave
it at zero. `ProfileOut` verifies the accepted mode and custom/manual input,
but does not report the actual fixed-mode trace period.

The authoritative actual trace period is:

```text
RTA_FrameInfo_TypeDef.PacketAcqTime / PacketFrame
```

`PacketAcqTime` is seconds. Invalid or unavailable packet timing is represented
as unavailable; the backend does not synthesize an actual value from the
request.

The application preserves requested fields separately:

- `sweep_time_mode`
- `sweep_time_multiple`
- `sweep_time_s` (manual target, seconds)

The actual state returns the verified mode, accepted multiple where meaningful,
and measured `sweep_time_s`.

## Application policy

The web application locks Sweep Time to `minimum` (`Fast / auto`). Sweep Time
is not advertised as a supported control, has no REST mutation endpoint, and
is not shown in the frontend. Window function now appears in the Bandwidth
section, so there is no separate Sweep section.

The native mappings and validation helpers remain available for standalone
hardware diagnostics. Actual sweep period remains in backend settings/status
telemetry for acquisition diagnostics, but is not user-selectable.

## Hardware observations

At approximately 60.306 kHz actual RBW, 3,328 points, and FFT size 4,096:

| Mode/request | Actual period | Approx. native trace rate |
|---|---:|---:|
| minimum | 32.768 µs | 30.6 ktrace/s |
| 2× | 65.536 µs | 15.4 ktrace/s |
| 4× | 131.072 µs | 7.67 ktrace/s |
| 10× | 327.680 µs | 3.12 ktrace/s |
| 20× | 655.360 µs | 1.60 ktrace/s |
| 50× | 1.6384 ms | 684 trace/s |
| custom 3× | 98.304 µs | 10.2 ktrace/s |
| custom 8× | 262.144 µs | 3.88 ktrace/s |
| custom 100× | 3.2768 ms | 380 trace/s |
| manual 10 ms | 9.99424 ms | 152 trace/s |

A custom `0.5×` request was accepted by the SDK but remained clamped at the
minimum actual period, so the application rejects custom values below `1×`.
Changing only Sweep Time did not change RBW, point count, or FFT size. At a
241.224 kHz actual RBW, the minimum period changed to 8.192 µs, confirming that
minimum sweep time is profile-dependent. No disconnects, timeouts, acquisition
errors, or IF-overflow events occurred in the short matrix.

The diagnostic is:

```bash
python3 backend/tools/test_san90_sweep_time.py --sample-seconds 0.5
```

It requires exclusive access to the physical SAN-90 and restores the
conservative minimum-sweep profile before disconnecting.
