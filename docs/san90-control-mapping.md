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
| IF AGC | `if_agc_enabled` | `RTA_Profile_TypeDef.EnableIFAGC`, `uint8_t` | `0` off, `1` on | Reduces IF gain when saturation occurs | Enable is verified from `ProfileOut.EnableIFAGC` | Runtime gain is reported separately by `MeasAuxInfo.IFAGCGain`. |
| IF AGC target | `if_agc_target_dbfs` | `Device_SetIFAGCTarget(void **, double *)` | `-30..0 dBFS`; the pointer returns the accepted value. SAN-90 accepted `-9.5` exactly. | None | Verified-at-apply through the in/out `double *`; there is no independent getter. | Does not alter software dBm calibration. |
| IF AGC period | `if_agc_period_s` | `Device_SetIFAGCPeriod(void **, double *)` | `-1..2147483 s`; negative is one-shot, zero dynamic, positive periodic. SAN-90 accepted `0.25` exactly. | Mode follows the sign/value | Verified-at-apply through the in/out `double *`; there is no independent getter. | Does not alter software dBm calibration. |
| VBW | `vbw_mode`, `vbw_hz` | `RTA_Profile_TypeDef.VBWMode`, enum/`int`; `VBW_Hz`, `double` Hz | Native mappings are Manual 0, RBW 1, 0.1× RBW 2, 0.01× RBW 3, 10× RBW/bypass 4. The application exposes only RBW and 0.1× RBW, defaulting to 0.1×. | Ratio modes use actual RBW | Both mode and Hz from returned `ProfileOut`; ratio values are never synthesized as readback | Narrow VBW reduces trace rate/smooths output; it does not change point count. |
| Sweep Time | fixed `minimum` | `RTA_Profile_TypeDef.SweepTimeMode`, `int`; `SweepTime`, `double` | The native mappings remain documented and diagnostic-tested, but the application locks mode 0 (`minimum`) and exposes no control. | Minimum is RBW/profile dependent | Actual period remains available internally from `RTA_FrameInfo.PacketAcqTime / PacketFrame` | The fixed minimum avoids user-selected trace-rate reductions. |

## Ambiguities deliberately preserved

- No SDK capability function or header constants provide the SAN-90 center-frequency range, center-frequency step, reference-level range, reference-level step, or supported manual attenuation values.
- `Device_GetAmpAttenState` reports current state; it does not enumerate valid attenuation settings.
- The first post-restart `RTA_GetRealTimeSpectrum_Raw` result is the authoritative source for the new `ScaleTodBm` and `OffsetTodBm`. They are not fields of `RTA_ProfileOut`.
- Requested values are never reported as actual until `RTA_Configuration` succeeds and a valid raw frame is received under the new configuration generation.
- `MeasAuxInfo_TypeDef.IFAGCGain` is a runtime-only `double` in dB. Positive
  means amplification and negative means attenuation. It is sampled from
  acquisition auxiliary data at 10 Hz and becomes unavailable after one
  second without a fresh sample.
