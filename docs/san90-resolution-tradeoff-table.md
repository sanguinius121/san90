# SAN-90 resolution trade-off operating points

Measured 2026-07-20 on SAN-90 firmware MCU/FPGA 0.55.103 with HTRA API 0.55.88. Center frequency was 2.45 GHz, reference level 0 dBm, automatic attenuation, preamplifier off, Blackman–Nuttall window, and positive-peak detector. Each final activation request was measured for five seconds. The safe auto-RBW configuration was restored after discovery.

The slider order is deliberately time priority to frequency priority. Auto RBW is separate and is not a slider step.

| Index | Activation request | Actual RBW | Points | FFT | SDK traces/s | Bin spacing | Spectrum publish | WebGL target | Waterfall rows/s | Rows/batch | Traces/row | Time/row | Actual span |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 8,000 kHz | 7.719180 MHz | 26 | 32 | 979,040 | 3.906250 MHz | 60 FPS | 60 FPS | 480 | 8 | 2,039.67 | 2.083 ms | 101.5625 MHz |
| 1 | 4,000 kHz | 3.859590 MHz | 52 | 64 | 489,252 | 1.953125 MHz | 60 FPS | 60 FPS | 480 | 8 | 1,019.28 | 2.083 ms | 101.5625 MHz |
| 2 | 2,000 kHz | 1.929795 MHz | 104 | 128 | 244,764 | 976.563 kHz | 60 FPS | 60 FPS | 480 | 8 | 509.93 | 2.083 ms | 101.5625 MHz |
| 3 | 1,000 kHz | 964.897 kHz | 208 | 256 | 122,382 | 488.281 kHz | 60 FPS | 60 FPS | 480 | 8 | 254.96 | 2.083 ms | 101.5625 MHz |
| 4 | 500 kHz | 482.449 kHz | 416 | 512 | 61,191 | 244.141 kHz | 60 FPS | 60 FPS | 480 | 8 | 127.48 | 2.083 ms | 101.5625 MHz |
| 5 | 300 kHz | 241.224 kHz | 832 | 1,024 | 30,595.5 | 122.070 kHz | 60 FPS | 60 FPS | 240 | 4 | 127.48 | 4.167 ms | 101.5625 MHz |
| 6 | 150 kHz | 120.612 kHz | 1,664 | 2,048 | 15,297.5 | 61.035 kHz | 60 FPS | 60 FPS | 120 | 2 | 127.48 | 8.333 ms | 101.5625 MHz |
| 7 | 50 kHz | 60.306 kHz | 3,328 | 4,096 | 7,647.5 | 30.518 kHz | 60 FPS | 60 FPS | 60 | 1 | 127.46 | 16.667 ms | 101.5625 MHz |

The 480-row policy is a renderer-friendly cap. The four widest profiles continue acquiring at 122–979 ktraces/s, but integrate approximately 255–2,040 traces into each displayed 2.083 ms row. Native acquisition interval and displayed waterfall-row duration are distinct.

With a fixed five-second visible viewport, the steps display 2,400 rows for indices 0–4, then 1,200, 600, and 300 rows. Texture storage remains 4,096 rows and does not define visible duration.

## Hardware coercion discovered

| Exploratory requested RBW | Actual operating point | Slider representation |
|---|---|---|
| 15, 30, 50, 75 kHz | 60.306 kHz / 3,328 points / FFT 4,096 | one step, activated with 50 kHz |
| 100, 150 kHz | 120.612 kHz / 1,664 points / FFT 2,048 | one step, activated with 150 kHz |
| 200, 300 kHz | 241.224 kHz / 832 points / FFT 1,024 | one step, activated with the already verified 300 kHz request |
| 500 kHz | 482.449 kHz / 416 points / FFT 512 | one step |
| 1 MHz | 964.897 kHz / 208 points / FFT 256 | one step |
| 2 MHz | 1.929795 MHz / 104 points / FFT 128 | one step |
| 4 MHz | 3.859590 MHz / 52 points / FFT 64 | one step |
| 8 MHz | 7.719180 MHz / 26 points / FFT 32 | one step |

All exploratory requests succeeded. Duplicate requested values are not exposed as separate slider positions.

## Auto baseline

Auto RBW returned 60.306 kHz, 3,328 points, FFT 4,096, and approximately 7,642–7,646 traces/s during discovery. Auto remains a separate mode and retains the verified 60-row/s safe behavior.

## Measurement notes

- Start/stop frequencies were 2.39921875 GHz and 2.50078125 GHz for every measured point.
- Native amplitude mapping remained monotonic with `ScaleTodBm = 0.5`; `OffsetTodBm` changed by configuration, as expected, and must remain generation-scoped.
- First-valid-frame transaction latency was approximately 109–113 ms.
- Bin spacing is actual span divided by returned display point count.
- POI is not inferred from trace rate, row duration, or rendering rate. The trade-off capability leaves POI nullable.
- Spectrum publication and rendering remain fixed at 60 FPS. Waterfall production remains adaptive, and the v4 spectrum-temporal path has been validated on real hardware at every profile.
