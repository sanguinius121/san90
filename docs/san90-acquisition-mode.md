# SAN-90 standalone acquisition mode

## Selected mode: RTA continuous spectrum

The standalone diagnostic uses the SDK's RTA mode, following [`RTAMode_Standard.cpp`](../harogic/C_Examples-4/C++_Examples/Examples/RTAMode_Standard.cpp) and the canonical [`htra_api.h`](../harogic/Linux_API/htraapi/inc/htra_api.h). The relevant calls are `RTA_ProfileDeInit`, `RTA_Configuration`, `RTA_BusTriggerStart`, repeated polling with `RTA_GetRealTimeSpectrum_Raw`, and `RTA_BusTriggerStop`.

RTA was selected because the SAN-90 performs the spectrum processing in hardware, returns consecutive spectrum traces continuously, reports actual frequency and resolution metadata, and maps directly to a live spectrum plus waterfall. It avoids recomputing an FFT from IQ samples. SWP remains appropriate for panoramic spans beyond the instantaneous RTA bandwidth, but it is not the mode used by this diagnostic.

## Data contract

- **Native trace type:** caller-allocated `uint8_t[PacketValidPoints]`.
- **Trace layout:** `PacketFrame` consecutive traces, each containing `FrameWidth` bins. The diagnostic validates `PacketValidPoints >= PacketFrame × FrameWidth`.
- **Application type:** contiguous NumPy `float32`, converted vectorially as `trace_byte × ScaleTodBm + OffsetTodBm`.
- **Amplitude unit:** dBm.
- **Point count:** configuration-dependent and returned in `RTA_FrameInfo_TypeDef.FrameWidth`; the verified SAN-90 configuration returned 3,328 bins, not a fixed 1,024.
- **Frequency metadata:** `StartFrequency_Hz`, `StopFrequency_Hz`, center derived from those values, actual `RBW_Hz`, `VBW_Hz`, POI, FFT size, and packet/frame dimensions.
- **Time metadata:** `MeasAuxInfo.nsSinceEpoch` for the packet and `FrameInfo.TraceTimestampStep` for consecutive traces. The SDK exposes no universal trace sequence, so the application assigns a monotonic sequence after each successful trace conversion.
- **Other metadata:** maximum bin/power, temperature, RF/baseband state, density bitmap index when using the non-raw call, gain state, packet acquisition time, and time resolution.

## Acquisition behavior and ownership

The API is blocking polling, not a callback. `RTA_GetRealTimeSpectrum_Raw` may wait up to `RTA_Profile_TypeDef.BusTimeout_ms`; status `-10` is a bus timeout and `-304` means data is not ready. The SDK owner thread performs every handle-based call, so no blocking SDK call runs on FastAPI or asyncio.

The native spectrum array is allocated and owned by the application, but the SDK overwrites it on the next read. The byte array is therefore converted into a separate float32 NumPy array before publication. The latest-frame and interval max-hold buffers own detached copies; no SDK buffer-release function is required for the non-encapsulated RTA API.

The connected device currently returns `nsSinceEpoch` values that are not aligned with the host Unix epoch, likely because an absolute device/GNSS time source is not established. The original SDK timestamp is preserved as metadata, but live frame-age reporting uses a local monotonic receipt timestamp. Consumers must not treat the SDK timestamp as host UTC until time synchronization is verified.

## Measured rate

With HTRA API 0.55.88, SAN-90 MCU/FPGA 0.55.103, 1 GHz center, the SDK's default decimation/RBW, and a 101.5625 MHz returned span, the device produced approximately 7,000–7,400 spectrum trace frames per second at 3,328 points per trace. `RTA_GetRealTimeSpectrum_Raw` returns multiple traces per packet, so packet-call rate and trace-frame rate are reported separately. The browser display path must intentionally retain only the latest trace and interval max-hold instead of queueing all hardware traces.
