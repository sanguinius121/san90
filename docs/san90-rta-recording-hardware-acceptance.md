# SAN-90 recording backend and hardware acceptance

Date: 2026-07-29  
Device: HAROGIC SAN-90, UID `5922321526757720115`  
Firmware/FPGA/API: `0.55.103` / `0.55.103` / `0.55.88`

## Implementation

The real recorder branch is in `San90Source._acquire_packet_on_owner`, after
the existing spectrum, waterfall, and AI consumers. The common
stop/configure/readback/restart transaction reports one
`RECONFIGURATION_PAUSE`; the following packet writes a decode fingerprinted
CONFIG before its TRACE. A generation-local sequence reset is explicitly
marked and does not create a second unexplained discontinuity.

Native `ScaleTodBm` and `OffsetTodBm` are captured directly from
`RTA_PlotInfo`. Software Amplitude Offset is stored separately. Device timing
is packet-level; the nominal per-trace period is derived only from valid
`PacketAcqTime / PacketFrame`. Raw SDK timer fields are preserved without
claiming a host epoch.

Persistent preferences use `config/recording.json`, schema 1. The output is a
safe relative subdirectory below the backend-owned `~/SAN90_Recordings` root,
which can be overridden with `SAN90_RECORDING_ROOT`. The
backend owns one recorder shared by simulator and hardware sources; shutdown
requests bounded finalization for up to five seconds. Disconnect does not
auto-resume a completed recording.

## Short physical runs

All files below were parsed by `San90RtaReader` with payload CRC enabled.

| Test | Result | Size | Traces / batches | Configs | Gaps / lost / rejected |
|---|---|---:|---:|---:|---:|
| Fixed 5 s | clean `fixed_duration` | 84,788,679 B | 25,422 / 1,338 | 1 | 0 / 0 / 0 |
| Manual ~5 s | clean `user_stop`; repeated stop harmless | 84,852,045 B | 25,441 / 1,339 | 1 | 0 / 0 / 0 |
| Center tune 2.45 → 2.44 GHz | one file, valid ordering | 34,096,778 B | — | 4 | 1 pause / 0 / 0 |
| Scan 400 MHz, 900 MHz, 2.44 GHz | all centers in one file | 20,156,072 B | — | 4 | 3 pauses / 0 / 0 |
| Amplitude Offset 0 → 3 dB | same generation gets new CONFIG | 34,031,700 B | — | 2 | 0 / 0 / 0 |
| Controlled source stop | clean `device_disconnect`; no auto-resume | 16,984,925 B | 5,092 / 268 | 1 | 0 / 0 / 0 |

The fixed run averaged 16.15 MB/s of raw samples at 3,328 points. Its queue
high-water was 126,464 bytes and two items. The manual run high-water was
63,232 bytes and one item. Acquisition errors and timeouts remained unchanged
at zero. Spectrum/waterfall and the bound AI GRAY8 publisher remained active;
no frontend code or binary spectrum protocol changed.

The observed rate is lower than the historical 3,328-point measurement of
approximately 25.45 MB/s. Because the recorder queue remained nearly empty
with no rejection/loss, this does not indicate disk-writer saturation, but the
profile/runtime discrepancy should be investigated separately.

The disconnect test used the managed analyzer stop API rather than physically
hot-unplugging USB, avoiding repeated device disruption. It validates the same
backend recorder lifecycle but is not a physical USB-removal test.

## Frontend Record API hardware acceptance

After the sidebar Record panel was implemented, the same REST operations used
by the UI were revalidated on the physical SAN-90 on 2026-07-29. SAStudio4 was
closed before the managed backend reclaimed the device.

| UI flow | Result | Size | Traces / batches | Configs | Gaps / lost / rejected |
|---|---|---:|---:|---:|---:|
| Fixed 5 s | clean `fixed_duration` | 84,852,838 B | 25,441 / 1,339 | 2 | 0 / 0 / 0 |
| Manual 5 s + repeated OFF | clean `user_stop`; second OFF returned the same completion | 84,855,209 B | 25,441 / 1,339 | 5 | 0 / 0 / 0 |
| Manual + 2.45 → 2.44 GHz tune | one clean file with generations 1 and 2 | 34,095,196 B | — | 2 | 1 pause / 0 / 0 |
| Manual + 400/900/2440 MHz scan | all centers in one clean file | 17,875,614 B | 5,358 / 282 | 5 | 3 pauses / 0 / 0 |

The Fixed run averaged 16.74 MB/s raw data and reached only 63,232 queued
bytes/one item. Reader and inspection CLI validation found no CRC, ordering,
counter, or END issue. During the scan, spectrum and waterfall publication
remained 60 FPS and the AI stream created eight additional images. Acquisition
errors and timeouts stayed at zero throughout all four runs.

The backend can finalize quickly enough that its `stopping` or `finalizing`
state may exist for less than one 250 ms active polling interval. The frontend
therefore presents its immediate STARTING/STOPPING request transition and then
continues using backend status as authoritative.

After the runs, recording preferences were restored to Fixed/5 seconds,
4 GiB limit, 2 GiB reserve, output `.`, prefix `SAN90_RTA`. Frequency Scan was
restored to its six saved disabled entries, center frequency to 2.45 GHz, and
VBW remained locked/read back at `0.1 × RBW`.

## Remaining work

- Add recording-file listing/deletion/download controls and future playback.
- Investigate the current 16.15 MB/s versus historical 25.45 MB/s raw-rate
  difference before setting a UI throughput expectation.
- Perform a physical hot-unplug test only if USB-loss behavior itself becomes
  acceptance scope.
- Playback remains unimplemented; the files are not SAStudio `.rtspectrum`.
