# SAN-90 RTA VBW controls

## SDK mapping

HTRA API 0.55.88 declares `VBWMode_TypeDef` in
`harogic/Linux_API/htraapi/inc/htra_api.h` lines 401–409:

| Native mode | SDK enum | Value | Meaning |
|---|---|---:|---|
| `manual` | `VBW_Manual` | 0 | Use `VBW_Hz` |
| `ratio-1` | `VBW_EqualToRBW` | 1 | VBW = actual RBW |
| `ratio-0.1` | `VBW_TenPercentRBW` | 2 | VBW = 0.1 × actual RBW |
| `ratio-0.01` | `VBW_OnePercentRBW` | 3 | VBW = 0.01 × actual RBW |
| `ratio-10` | `VBW_TenTimesRBW` | 4 | VBW = 10 × actual RBW; filter bypass |

`RTA_Profile_TypeDef.VBW_Hz` is a `double` in Hz and `VBWMode` is the native
enum (`int` ABI) at header lines 1123 and 1132. There is no VBW Auto enum.
`RTA_Configuration` returns both accepted fields in `ProfileOut`, which is the
actual-value source.

VBW uses the existing owner-thread stop/configure/readback/start transaction.
The application fixes `VBWMode` at 0.1× RBW for consistent AI-image timing and
appearance. VBW mode/value are not advertised as writable controls and
non-fixed requests are rejected before hardware configuration.

## Hardware behavior

On 2026-07-28, SAN-90 model 67, firmware 0.55.103, accepted all five enums in
RTA with SDK status 0. Tests used 2.45 GHz, 0 dBm reference level, automatic
attenuation, preamplifier off, automatic or selected manual RBW, and a safe
input condition.

Auto RBW returned `60,306.09130859375 Hz`:

| Mode | Returned VBW | Approx. native traces/s | Points |
|---|---:|---:|---:|
| Manual 60,306.091 Hz | 60,306.091 Hz | 3,922 | 3,328 |
| RBW | 60,306.091 Hz | 3,925 | 3,328 |
| 0.1 × RBW | 6,030.609 Hz | 1,393 | 3,328 |
| 0.01 × RBW | 603.061 Hz | 253 | 3,328 |
| 10 × RBW | 603,060.913 Hz | 7,722 | 3,328 |

With requested 300 kHz manual RBW, the hardware returned
`241,224.365234375 Hz`, 832 points, and ratio VBWs of `2,412.244`,
`241,224.365`, and `2,412,243.652 Hz` for 0.01×, 1×, and 10× respectively.
Changing VBW did not change point count; changing RBW retained its existing
profile-defined point count.

Manual observations:

- `12,345.67 Hz`, `60.31 Hz`, 10 MHz, and 100 MHz returned exactly.
- A request below actual RBW/1000 was coerced upward. At auto RBW, 1 Hz and
  60 Hz both returned `60.30609130859375 Hz`.
- 1 GHz and 10 GHz requests returned 200 MHz. The application therefore
  validates a conservative hardware-tested request range of 1 Hz–200 MHz.
- The native field is a continuous `double`; the UI button step is 1 Hz but
  typed fractional values are preserved.
- Narrower VBW reduced native trace rate and could increase configuration time
  while waiting for the first valid trace. No acquisition errors, timeouts,
  unexpected disconnects, or IF overflow occurred.

The standalone short diagnostic is:

```bash
python3 backend/tools/test_san90_vbw.py --sample-seconds 0.3
```

## UI behavior

The Bandwidth panel has no VBW selector or adjustment buttons. Its read-only
VBW field displays the actual returned `ProfileOut.VBW_Hz` value in a compact
engineering unit and refreshes through analyzer-settings polling. RBW changes
update VBW only from returned analyzer settings.
