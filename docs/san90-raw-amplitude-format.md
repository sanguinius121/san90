# SAN-90 raw RTA amplitude format

`RTA_GetRealTimeSpectrum_Raw` writes relative spectrum power codes into a caller-owned `uint8_t` buffer. The codes are not dBm by themselves. For every returned packet, `RTA_PlotInfo_TypeDef` supplies:

- `ScaleTodBm`: dB represented by one raw code;
- `OffsetTodBm`: dBm represented by raw code zero.

The verified conversion from the SDK header and examples is:

```text
power_dBm = raw_uint8 × ScaleTodBm + OffsetTodBm
```

The backend preserves both values with the acquisition metadata and converts display spectrum snapshots with vectorized NumPy operations into contiguous float32. It does not run a Python loop over bins.

For the verified SAN-90 RTA configurations, `ScaleTodBm` is finite and positive. Therefore the mapping is monotonic and:

```text
max(convert(raw traces)) == convert(max(raw traces))
```

The high-rate path can consequently accumulate interval max-hold directly in reusable uint8 buffers. Only the display-rate spectrum snapshot (60 FPS by default) is converted to float32; the interval max-hold remains uint8 for the waterfall LUT.

The mapping is configuration-dependent. Reference level, attenuation, preamplifier/gain configuration, RBW-related configuration, or another device reconfiguration may change scale or offset. The accumulator compares the mapping on each packet. If it changes, the current max-hold interval is reset before mixing codes from different mappings. Actual reference level and the current scale/offset travel with every display snapshot.

The native SDK byte buffer belongs to the application but is overwritten by the next SDK read. The acquisition owner copies only the latest trace and packet max into fixed-size application buffers before the next poll. No per-frame SDK release call is required.
