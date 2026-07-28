# HAROGIC SAN-90 SDK analysis

## SDK update: HTRA API 0.55.88

The SDK was replaced after the original Phase 1 analysis. The current repository package contains 184 files under [`harogic/`](../harogic/) and identifies itself as **HTRA API 0.55.88** (`Major_Version=0`, `Minor_Version=55`, `Increamental_Version=88`). Current authoritative artifacts are:

- [`htra_api.h`](../harogic/Linux_API/htraapi/inc/htra_api.h)
- [`libhtraapi.so.0.55.88`](../harogic/Linux_API/htraapi/lib/x86_64/libhtraapi.so.0.55.88)
- [`RTAMode_Standard.cpp`](../harogic/C_Examples-4/C++_Examples/Examples/RTAMode_Standard.cpp)
- [`RTA_GetRealTimeSpectrum_Standard.py`](../harogic/Python_Examples-1/Python_Examples/RTA_GetRealTimeSpectrum_Standard.py)

`Get_APIVersion()` returns 0.55.88. `APISupportFirmwareVersions()` lists the connected SAN-90's exact MCU/FPGA baseline, **0.55.103 / 0.55.103**, so the former `Device_Open` status `-49` compatibility blocker is resolved.

The Phase 5 ctypes subset was revalidated against the new canonical header. `BootProfile_TypeDef`, `DeviceInfo_TypeDef`, `DeviceFirmwareVersion_TypeDef`, `BootInfo_TypeDef`, `MeasAuxInfo_TypeDef`, `TriggerInfo_TypeDef`, `RTA_Profile_TypeDef`, `RTA_FrameInfo_TypeDef`, and `RTA_PlotInfo_TypeDef` retain the sizes and offsets used by the application. The new header contains a fixed-underlying-type enum (`enum dB_unit : uint8_t`), so the ABI probe now compiles the header as C++11 rather than C11.

### Phase 5 hardware verification

A three-second standalone RTA diagnostic completed successfully with conservative settings: 1 GHz center, 0 dBm reference level, preamplifier forced off, SDK-default automatic attenuation and RBW. Actual returned values were:

- model 67, MCU/FPGA 0.55.103, API 0.55.88;
- start 949.21875 MHz, stop 1.05078125 GHz, span 101.5625 MHz;
- RBW 60.306091 kHz and 3,328 points per trace;
- 22,895 SDK trace frames in 3.102 seconds, approximately 7,380 trace frames/s;
- measured range -105.380 to -69.380 dBm, mean -85.522 dBm;
- zero acquisition errors and clean trigger/device shutdown.

The diagnostic observed 1,639 latest frames while 21,255 were intentionally replaced in the bounded one-slot display buffer. This confirms that the source must preserve the latest trace and interval max-hold rather than queue every hardware trace.

The remainder of this document records the original HTRA API 0.55.82 discovery and should be treated as historical where version numbers, paths, supported firmware, or package contents differ. The architectural conclusions about RTA polling, caller-owned buffers, NumPy conversion, and a single SDK owner thread remain applicable.

---

Phase 1 discovery report. No device configuration or acquisition calls were made while producing this report.

## Scope and authoritative sources

The supplied path `/harogic` is not present at the filesystem root. The SDK inspected is the repository directory [`harogic/`](../harogic/), containing 868 files. The primary sources used were:

- [`htra_api.h`](../harogic/Linux/Install_HTRA_SDK/htraapi/inc/htra_api.h), the canonical C ABI header. All 18 copies of this header in the package have the same SHA-256 hash.
- [`libhtraapi.so.0.55.82`](../harogic/Linux/Install_HTRA_SDK/htraapi/lib/x86_64/libhtraapi.so.0.55.82) and its exported symbols.
- [`HAROGIC HTRA API Programming Guide V0.55.82.pdf`](../harogic/Application%20Manual/HAROGIC%20HTRA%20API%20Programming%20Guide%20V0.55.82.pdf).
- [`HAROGIC HTRA API Examples Usage Guide V1.0.pdf`](../harogic/Application%20Manual/HAROGIC%20HTRA%20API%20Examples%20Usage%20Guide%20V1.0.pdf).
- [`HAROGIC Spectrum Analyzer Quick Start Guide V1.4.pdf`](../harogic/Application%20Manual/HAROGIC%20Spectrum%20Analyzer%20Quick%20Start%20Guide%20V1.4.pdf).
- Linux C++ examples [`RTAMode_Standard.cpp`](../harogic/Linux/HTRA_C++_Examples/Examples/RTAMode_Standard.cpp), [`RTAMode_Standard_perframe.cpp`](../harogic/Linux/HTRA_C++_Examples/Examples/RTAMode_Standard_perframe.cpp), and [`SWP_GetSpectrum_Standard.cpp`](../harogic/Linux/HTRA_C++_Examples/Examples/SWP_GetSpectrum_Standard.cpp).
- Bundled Python wrapper [`htra_api.py`](../harogic/Linux/HTRA_Python_Examples/htra_api.py) and Python SWP/RTA examples.

The official API guide has a likely changelog-date typo: it dates V0.55.82 as `04/13/2025`, while V0.55.77 and V0.55.79 are dated February and March 2026. The version number in the header, shared-library filename, runtime `Get_APIVersion()`, and guide title consistently identify this SDK as **0.55.82**.

## Executive conclusion

Use **RTA (real-time spectrum analysis)** for the application's normal real-time display and retain **SWP** as a second measurement mode for panoramic spans that exceed RTA's instantaneous analysis bandwidth.

RTA is hardware spectrum processing; Python must not recompute an FFT. Each `RTA_GetRealTimeSpectrum` poll returns:

- `PacketFrame` consecutive traces in a caller-allocated `uint8_t` array;
- `FrameWidth` points per trace and `PacketValidPoints = PacketFrame × FrameWidth`;
- a caller-allocated `uint16_t` hardware probability-density bitmap;
- scale and offset required to convert relative trace bytes to dBm;
- start/stop frequencies, POI, packet acquisition time, per-trace timestamp step, trigger timing, temperature, overload-related state, and other auxiliary metadata.

The recommended integration is **Option B: a maintained Python ctypes wrapper around the native library**. Do not use the supplied Python wrapper unchanged: it has material 0.55.82 ABI/API drift, detailed below. A corrected, header-verified wrapper plus a single owner/acquisition thread is the smallest evidence-supported path to the existing Python web backend. Reassess Option C only after measuring the real RTA packet rate and Python conversion/publish cost.

## Required findings

| # | Topic | Finding |
|---:|---|---|
| 1 | SDK version | HTRA API **0.55.82** (`Major_Version=0`, `Minor_Version=55`, `Increamental_Version=82`). `Get_APIVersion()` also returns 0.55.82 from the repository library. |
| 2 | Supported operating systems | The quick-start guide lists Windows 11/10/8/7 and Linux distributions Ubuntu 22.04/20.04/18.04, Debian 12/11/10, and Raspberry Pi OS 64-bit. The package contains Windows DLL/import libraries and Linux ELF libraries. |
| 3 | Supported SAN device families | The quick-start guide covers SAN/SAM, SAE/SAN-400, and all-new SAN families. The API's `DeviceClass_TypeDef` enumerates E90, E200, TRX60, ZRX200, N45/N60/N90, M60/M80, E310/E330, TX90/RX90, N150/N400, A24, C24, and a simulator. **SAN-90 corresponds to `Device_N90_R0 = 67` in the supplied header**; device selection should verify model 67 rather than infer it from a display name. |
| 4 | Required shared libraries | Core: `libhtraapi.so.0.55.82`. Its x86-64 ELF dependencies include `libusb-1.0.so.0`, `libliquid.so`, `libpthread`, `libdl`, `libstdc++`, `libm`, `libgomp`, `libgcc_s`, and libc. The SDK ships architecture-specific dependencies: x86-64 includes `libiomp5.so`, `libmkl.so`, `libliquid.so`, and `libusb`; AArch64 includes `libarmral.so`, `libliquid.so`, and `libusb`; ARMv7 includes `libliquid.so` and `libusb`. The install script also installs udev rules and `/etc/htrausb.conf`. |
| 5 | Python wrapper mechanism | Handwritten `ctypes`: `ctypes.CDLL("./htraapi/libhtraapi.so")`, `ctypes.Structure` declarations, and explicit `argtypes`/`restype`. NumPy is used by examples to view/copy ctypes arrays. No cffi wrapper or device-specific pybind layer is supplied. The GNU Radio pybind code wraps its GNU Radio source block, not the HTRA API itself. |
| 6 | Discovery and connection | For USB, initialize `BootProfile_TypeDef` (`PhysicalInterface=USB`, power mode), call `Device_List` to obtain device count, device IDs, and `DeviceInfo_TypeDef[]`, select the N90 model, then call `Device_Open(&Device, DevNum, &BootProfile, &BootInfo)`. `BootInfo` returns device UID/model/firmware, bus speed/version, API version, and startup warnings/errors. Ethernet uses `PhysicalInterface=ETH` plus IP version/address, port, and read timeout. Close with `Device_Close(&Device)`. |
| 7 | Measurement modes | SWP standard/panoramic spectrum, IQS IQ streaming, DET power detection, RTA real-time spectrum/density, PNM phase noise, MSCAN multi-band/list scanning, optional digital demodulation, zero-span, MPS/list mode, plus signal-generation functions on supported hardware. |
| 8 | Best mode for this application | **RTA** for the live spectrum, waterfall, density, and short FHSS/burst visibility. It provides multiple hardware spectrum frames per read and a density bitmap. Use **SWP** when a requested span cannot fit RTA's instantaneous bandwidth or when panoramic sweep measurements are required. |
| 9 | Trace data type | SWP returns caller-provided `double[]` frequency and `float[]` power in dBm. RTA returns relative power as `uint8_t[]`; convert vectorially using `dBm = byte × PlotInfo.ScaleTodBm + PlotInfo.OffsetTodBm`. RTA density is `uint16_t[]`. |
| 10 | Trace point count | Not a fixed 1024. SWP returns actual `FullsweepTracePoints` and `PartialsweepTracePoints`; a requested `TracePoints` is adjusted to the closest supported count. RTA returns actual `FrameWidth`, with `PacketFrame` traces per read and `PacketValidPoints = PacketFrame × FrameWidth`. The application must adapt/resample only if a display policy requires it. |
| 11 | Polling or callbacks | **Polling.** Acquisition functions are `SWP_GetPartialSweep`/`SWP_GetFullSweep`, `RTA_GetRealTimeSpectrum`/`_Raw`, `IQS_GetIQStream`, and `DET_GetPowerStream`. No acquisition callback registration exists in `htra_api.h`. Callback matches elsewhere are UI helpers or the unrelated liquid-DSP library. |
| 12 | Whether trace buffers require copying | The non-encapsulated SWP/RTA APIs write into caller-allocated arrays, so no extra copy is required for synchronous processing. A copy or double-buffer swap **is required before reusing the same array while another thread/WebSocket publisher still reads it**. For RTA, conversion from `uint8` to application `float32 dBm` necessarily produces or fills a float buffer; do it with NumPy, not a Python point loop. |
| 13 | Buffer ownership | For the recommended non-encapsulated SWP/RTA calls, the application owns and sizes the output arrays from `TraceInfo`/`FrameInfo`. No per-frame release call is documented. Encapsulated SWP structures can expose addresses stored in the device object, but the analogous RTA PM1 function is explicitly “not implemented yet”; do not base the integration on those pointers. |
| 14 | Required cleanup | In adaptive bus-triggered RTA: call `RTA_BusTriggerStop`, then `Device_Close`. In fixed acquisition, also stop the bus trigger before close. `Device_Close` releases resources allocated by `Device_Open`. Other modes have their matching stop functions. DSP/ADM subsystems have separate close functions only if opened. No release is needed for application-owned SWP/RTA arrays. |
| 15 | Thread safety | The SDK does **not document general thread safety**. Official device examples perform SDK calls serially. The multithread IQ example confines acquisition to one thread and hands copied data to processing/writer threads. Use one owner thread and serialize all device calls/configuration; do not invoke the same handle concurrently from FastAPI handlers. |
| 16 | Blocking calls | Data retrieval can block awaiting bus data or a trigger. `BusTimeout_ms` applies to IQS/DET/RTA and the return table defines `APIRETVAL_WARNING_BusTimeOut = -10`, `APIRETVAL_WARNING_DataNotReady = -304`, last-packet and missed-trigger statuses. `RTA_GetRealTimeSpectrum` is timed as a per-packet call in the official C++ example. It must run outside the asyncio event loop. SWP reads similarly wait for sweep/hop data, although SWP has no profile `BusTimeout_ms`. |
| 17 | Timestamps/sequence | `RTA_TriggerInfo.SysTimerCountOfFirstDataPoint` timestamps the first data point in a packet; `FrameInfo.TraceTimestampStep` timestamps subsequent traces. `MeasAuxInfo` provides `SysTimeStamp`, `AbsoluteTimeStamp`, and, in 0.55.82, `nsSinceEpoch`. `SpectrumBitmapIndex` is an index for density-map retrieval. SWP has `HopIndex` and a conditional `FrameIndex`. There is no documented universal monotonic frame-sequence field, so the application must assign its own sequence on successful reads. |
| 18 | Available metadata | Device model/UID/hardware and MCU/FPGA/bus/API versions; actual profiles returned from configuration; actual SWP start/bin bandwidth/analysis bandwidth/trace points/min sweep estimate; RTA start/stop, POI, time resolution, packet acquisition time, FFT size, frame width/height/count, density maximum, gain state; peak index/power; temperature; RF/baseband state; gain/conversion state; IF AGC gain; reference-clock offset; absolute/system/epoch time; GNSS location/altitude/health when available; bus speed and physical transfer rate API. |
| 19 | UI controls supported | **SWP:** start/stop or center/span, reference level, RBW/VBW values and modes, sweep time/mode, window, detector and trace detector, requested trace points, gain strategy, preamplifier, attenuation, IF AGC enable, trace hold, triggers. **RTA:** center frequency, reference level, RBW/VBW and modes, decimation (therefore accepted instantaneous span), window, sweep time/mode, detector/trace detector, gain strategy, preamplifier, attenuation, IF AGC enable, and rich triggers. `Device_SetIFAGCTarget` sets/readjusts the accepted target through an in/out pointer. Actual values must come from `ProfileOut`, `FrameInfo`/`TraceInfo`, and auxiliary data. |
| 20 | Missing/unsupported UI controls | Step frequency, previous span, and full span are application operations, not device settings. RTA has no direct span field; its actual start/stop must be read from `RTA_FrameInfo` after selecting decimation/other profile values. No SDK amplitude-offset control was found. IF-AGC gain is reported in `MeasAuxInfo` but has no setter because it is runtime state. IF-AGC target and period use `Device_SetIFAGCTarget` and `Device_SetIFAGCPeriod`, both with in/out `double *` values and no independent getter. Device-specific preamp modes and optional controls require model/capability validation. The SDK has no single generic capability-query API; capabilities must be derived conservatively from model/options, documented ranges, successful configuration, and returned actual profiles. |
| 21 | Expected acquisition rate | Configuration- and hardware-dependent; the SDK gives no fixed guaranteed FPS. RTA's internal trace rate can be computed from returned `PacketFrame / PacketAcqTime` (and checked with `TraceTimestampStep`), while API packet-call throughput must be measured. The supplied per-frame example measures 1000 `RTA_GetRealTimeSpectrum` calls but provides no benchmark result. Do not equate API packet FPS with trace FPS because one packet contains multiple traces. |
| 22 | Risks of Python | The bundled wrapper is incomplete and stale relative to the canonical 0.55.82 header; wrong ctypes layouts can cause native memory overwrite. The examples perform Python per-point conversion and plotting, unsuitable for full-rate RTA. Other risks are incorrect pointer signatures, cwd-dependent library loading, accidental loading of an older installed library, allocation/copy pressure, and GIL contention in Python-side processing. NumPy vectorization and preallocated buffers mitigate the data path, but ABI verification is mandatory. |
| 23 | Need for C++ later | Not demonstrated yet. The C API and caller-owned buffers are compatible with a dedicated Python ctypes acquisition thread and NumPy at a 20–30 FPS browser publish rate. A small C++ daemon becomes justified if measured native packet rates, conversion/density processing, stable shutdown of blocking calls, or Python/ctypes robustness cannot meet requirements. Keep it as a measured fallback, not the first implementation. |

## Critical SDK/package discrepancies

### Bundled Python wrapper is unsafe unchanged

The canonical 0.55.82 C structure `MeasAuxInfo_TypeDef` is **80 bytes** on x86-64. The bundled Python `ctypes` declaration is **48 bytes** and omits:

- `Altitude`
- `SATHealth`
- `IFAGCGain`
- `RefClkFreqOffset`
- `nsSinceEpoch`

Because acquisition functions receive a pointer to this output structure, the native 0.55.82 library can write beyond the Python object's allocated memory. This is a memory-safety issue, not merely missing metadata.

The Python wrapper also:

- omits a named `EnableIFAGC` field in `SWP_Profile_TypeDef` and `RTA_Profile_TypeDef` (padding happens to keep later x86-64 offsets aligned, but the setting is inaccessible);
- does not bind `Device_List`, `Device_Open_WithClass`, `Device_InitIFAGC`, `Device_SetIFAGCTarget`, `Device_SetIFAGCPeriod`, `Device_GetAmpAttenState`, `RTA_GetRealTimeSpectrum_Raw`, or other newer functions;
- loads `./htraapi/libhtraapi.so`, but the archive initially contains only the versioned file; `Py_Make.sh` must create the symlink and assumes root;
- contains an RTA example call that passes `Device` where the declared signature expects `pointer(Device)`;
- converts RTA bytes to dBm with a Python loop.

The new wrapper must be validated by compiling a small C/C++ size/offset probe against `htra_api.h` and comparing every ctypes structure used by the application.

### Installed library version mismatch

This host currently has `/opt/htraapi/lib/x86_64/libhtraapi.so.0.55.61`, while the repository SDK, headers, docs, and calibration delivery are 0.55.82. Runtime checks confirmed:

- installed `/opt` library: **0.55.61**;
- repository library: **0.55.82**.

The integration must load the intended 0.55.82 library by an explicit resolved path and reject any `Get_APIVersion()` mismatch before opening hardware. Do not rely on the global loader search path until the installed SDK is deliberately upgraded.

### Documentation inconsistencies to handle conservatively

- The Python structures lag the canonical header as described above.
- The guide lists RTA decimation as powers of two from 2 to 4096, while official RTA examples set `DecimateFactor = 1`. The default returned by `RTA_ProfileDeInit` and accepted `ProfileOut` must be treated as authoritative at runtime.
- The quick-start guide explicitly says maximum damage input power and maximum DC input must be taken from the product manual. A SAN-90 product-specific maximum-input specification was not found in this SDK package. Do not infer RF safety from `RefLevel_dBm` ranges.

## Recommended acquisition lifecycle

This is a discovery result, not yet an implementation:

1. Load the repository 0.55.82 shared library by absolute path and verify `Get_APIVersion()`.
2. Build a zero-initialized USB `BootProfile_TypeDef`; call `Device_List` and select model `Device_N90_R0` (67), optionally using `Device_Open_WithClass` only after its behavior is tested.
3. Call `Device_Open`; inspect all `BootInfo` errors/warnings, bus speed, model, UID, and firmware compatibility.
4. Call `RTA_ProfileDeInit` before overriding a minimal profile.
5. For the first diagnostic, follow the official adaptive bus-trigger pattern: center frequency explicitly set, conservative reference level, preamplifier forced off until input conditions are known, automatic attenuation, bus timeout, `TriggerMode=Adaptive`, and `TriggerSource=Bus`. Exact RF safety values remain unresolved pending the SAN-90 product manual.
6. Call `RTA_Configuration`; use only `ProfileOut` and `FrameInfo` to allocate buffers and report accepted settings.
7. Preallocate `uint8[PacketValidPoints]` and, when density is needed, `uint16[FrameHeight × FrameWidth]`; preallocate float32 working/output arrays.
8. Call `RTA_BusTriggerStart` once for adaptive mode, then poll `RTA_GetRealTimeSpectrum` on the owner thread.
9. Vectorially reshape bytes as `(PacketFrame, FrameWidth)`, convert to float32 dBm, preserve the latest trace, and accumulate interval max-hold across every returned trace.
10. On stop, issue `RTA_BusTriggerStop` from the serialized owner context and then `Device_Close` in a `finally` path.

For wide spans, configure SWP and assemble exactly `TotalHops` partial results using the returned `HopIndex` rather than assuming loop order or a fixed point count.

## Recommendation

### **B. Python ctypes/cffi wrapper around the native library**

Implement a small, application-owned **ctypes** binding for the exact subset of HTRA API 0.55.82 used by discovery, device information, SWP, and RTA. Generate or transcribe definitions only from the canonical header, add automated ABI size/offset tests, load the library by absolute path, and serialize all calls through one acquisition/command thread.

Why not the alternatives now:

- **A — Direct Python SDK integration:** rejected because the supplied wrapper is demonstrably ABI-incomplete and missing required discovery/newer APIs.
- **C — Native C++ daemon:** technically viable and possibly useful later, but the SDK provides no evidence yet that Python with preallocated NumPy buffers cannot sustain the 20–30 FPS display path.
- **D — Other:** GNU Radio/Soapy integrations target IQ streaming and would add an unnecessary translation layer for hardware-generated RTA spectrum/density data.

## Unresolved before Phase 2/first hardware milestone

1. Obtain the SAN-90 product-specific manual/specification for maximum safe CW input and DC input.
2. Decide whether `/opt/htraapi` will be upgraded or the backend will use a private absolute 0.55.82 library path; the latter is safer initially.
3. Verify the N90's accepted RTA defaults, instantaneous span per decimation, `FrameWidth`, `PacketFrame`, packet rate, POI, and USB bus speed on hardware.
4. Verify how quickly `RTA_BusTriggerStop` interrupts a blocked read and define the shutdown timeout/recovery policy.
5. Verify whether RTA configuration can be changed while acquisition is active. The documentation does not explicitly guarantee this; initial integration should stop, configure, and restart.
6. Determine model-specific support for IF AGC, preamplifier gain modes, and any optional trigger/GNSS features from actual returned device information and configuration results.

## Phase 1 verification commands

```bash
# Inventory
find harogic -type f | sort

# Relevant APIs and wrappers
rg -n -i 'rta|real.?time|spectrum|trace|frame|callback|sweep|detector|iq' harogic
rg -n -i 'ctypes|cffi|CDLL|POINTER|numpy|as_array|pybind' harogic

# Canonical version and native exports
rg -n 'Major_Version|Minor_Version|Increamental_Version' \
  harogic/Linux/Install_HTRA_SDK/htraapi/inc/htra_api.h
nm -D --defined-only \
  harogic/Linux/Install_HTRA_SDK/htraapi/lib/x86_64/libhtraapi.so.0.55.82 \
  | rg 'Device_|SWP_|RTA_|IQS_|DET_'

# Official guide as searchable text
pdftotext -layout \
  'harogic/Application Manual/HAROGIC HTRA API Programming Guide V0.55.82.pdf' \
  /tmp/htra-api-guide.txt
```

Expected result: API/header/library version 0.55.82; polling-based SWP/RTA exports; `Device_N90_R0 = 67`; and RTA metadata/trace sizing matching the findings above.

## Next recommended step

After review/approval of this report, begin Phase 2 only: define the common backend `AnalyzerSource` contract and adapt the existing simulator without touching the renderer or attempting hardware acquisition. In parallel, the first ctypes binding work must start with ABI tests that reproduce the native 80-byte `MeasAuxInfo_TypeDef` on x86-64.
