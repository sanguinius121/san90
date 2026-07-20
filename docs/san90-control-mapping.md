# SAN-90 first-control SDK mapping

Primary evidence is the SDK 0.55.88 header `harogic/Linux_API/htraapi/inc/htra_api.h`, the shipped RTA examples, and the already verified `San90Source` ctypes ABI. All controls below are members of `RTA_Profile_TypeDef`; `RTA_Configuration` returns the accepted profile in `ProfileOut` and actual frequency bounds in `RTA_FrameInfo_TypeDef`.

The SDK examples call `RTA_ProfileDeInit`, populate the profile, call `RTA_Configuration`, and only then call `RTA_BusTriggerStart`. Neither the header nor examples document `RTA_Configuration` as safe while the RTA bus trigger is active. This application therefore stops RTA, reconfigures, recreates its buffers, and restarts for every control in this milestone.

| Frontend control | Application field | SDK field/type | Verified values or range | Automatic behavior | Actual readback | Raw amplitude effect |
|---|---|---|---|---|---|---|
| Center frequency | `center_frequency_hz` | `RTA_Profile_TypeDef.CenterFreq_Hz`, `double` | Header supplies no SAN-90 range or step. Values must be finite and positive; device acceptance is authoritative. The third-party Soapy example's 9 kHz–40 GHz constants are not advertised as SAN-90 capabilities and are not exposed by this application. | None documented | `ProfileOut.CenterFreq_Hz`; actual start/stop from `RTA_FrameInfo_TypeDef.StartFrequency_Hz` and `StopFrequency_Hz` | May select a different RF path/gain pattern, so scale/offset are refreshed from the first new raw frame. |
| Reference level | `reference_level_dbm` | `RTA_Profile_TypeDef.RefLevel_dBm`, `double` | Header supplies no device-specific range or step. Values must be finite; device acceptance is authoritative. The error-handling example adjusts it in 5 dB increments, but this is an example policy, not a declared device step. | None documented | `ProfileOut.RefLevel_dBm` | Can change `RTA_PlotInfo_TypeDef.ScaleTodBm` and `OffsetTodBm`; max-hold and waterfall must reset. |
| RF attenuation | `attenuation_db` / explicit auto mode | `RTA_Profile_TypeDef.Atten`, `int8_t` | `-1` is explicitly documented as automatic. The SDK publishes no SAN-90 manual attenuation list. Manual requests must fit non-negative `int8_t`; actual device acceptance/readback is authoritative. | `-1` means automatic | `ProfileOut.Atten` | Can change RF gain and therefore the raw-code scale/offset; reset required. |
| Preamplifier | `preamplifier` | `RTA_Profile_TypeDef.Preamplifier`, `PreamplifierState_TypeDef` | `auto`=`AutoOn` 0; `off`=`ForcedOff` 1; `low`=`OnLowGain` 2; `medium`=`OnMediumGain` 3; `high`=`OnHighGain` 4 | `auto` allows automatic enable | `ProfileOut.Preamplifier` | Changes RF gain; scale/offset and accumulated waterfall are invalidated. |
| Gain strategy | `gain_strategy` | `RTA_Profile_TypeDef.GainStrategy`, `GainStrategy_TypeDef` | `low-noise`=`LowNoisePreferred` 0; `high-linearity`=`HighLinearityPreferred` 1 | No separate automatic value | `ProfileOut.GainStrategy` | Changes gain selection; scale/offset and accumulated waterfall are invalidated. |

## Ambiguities deliberately preserved

- No SDK capability function or header constants provide the SAN-90 center-frequency range, center-frequency step, reference-level range, reference-level step, or supported manual attenuation values.
- `Device_GetAmpAttenState` reports current state; it does not enumerate valid attenuation settings.
- The first post-restart `RTA_GetRealTimeSpectrum_Raw` result is the authoritative source for the new `ScaleTodBm` and `OffsetTodBm`. They are not fields of `RTA_ProfileOut`.
- Requested values are never reported as actual until `RTA_Configuration` succeeds and a valid raw frame is received under the new configuration generation.
