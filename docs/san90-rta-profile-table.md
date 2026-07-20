# SAN-90 RTA measured bandwidth/profile table

HTRA API 0.55.88 exposes no finite RTA-profile identifier. The rows below are documented numeric RBW requests and verified RTA enum choices measured on SAN-90 MCU/FPGA 0.55.103 at 2.45 GHz center, 0 dBm reference, automatic attenuation, preamplifier off, low-noise gain, and 101.5625 MHz actual span. Each row was measured for approximately 0.5 seconds after a valid post-restart frame. The safe SDK-default configuration was restored afterward.

## RBW requests

| Identifier | Requested RBW | Actual RBW | Points / FFT | Actual span | SDK traces/s | Effective points/s | Scale | Offset | First valid / reconfiguration |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rbw:auto` | auto | 60,306.091 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,704 | 25.64 M | 0.5 | -112.956 dBm | 112.4 ms |
| `rbw:manual:15000` | 15,000 Hz | 60,306.091 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,705 | 25.64 M | 0.5 | -112.998 dBm | 110.5 ms |
| `rbw:manual:50000` | 50,000 Hz | 60,306.091 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,704 | 25.64 M | 0.5 | -112.976 dBm | 111.1 ms |
| `rbw:manual:300000` | 300,000 Hz | 241,224.365 Hz | 832 / 1,024 | 101.5625 MHz | 30,731 | 25.57 M | 0.5 | -100.916 dBm | 110.4 ms |

At the 60 FPS display rate, a live binary WebSocket acceptance run measured 1,020,757 bytes/s and 122.7 messages/s for the 3,328-point auto/Blackman–Nuttall configuration. The 832-point manual-300-kHz configuration measured 264,031 bytes/s and 121.9 messages/s. Both spectrum and waterfall publishers held 60 FPS, with the extra messages coming from periodic runtime status. Interval-counted SDK rates were 7,634.9 and 30,544.8 traces/s respectively. Process CPU samples during the same run varied with scheduling and reconfiguration; steady samples were approximately 20–40% at 3,328 points and 28–35% at 832 points, so these are observational ranges rather than device-profile guarantees.

## Auto-RBW window measurements

| Window | Actual RBW | Points / FFT | Span | SDK traces/s | Scale | Offset | Reconfiguration |
|---|---:|---:|---:|---:|---:|---:|---:|
| flat-top | 115,058.899 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,791 | 0.5 | -112.932 dBm | 113.0 ms |
| blackman-nuttall | 60,306.091 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,706 | 0.5 | -112.980 dBm | 111.4 ms |
| low-sidelobe | 67,607.422 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,671 | 0.5 | -113.008 dBm | 112.7 ms |
| rectangular | 30,517.578 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,704 | 0.5 | -112.955 dBm | 111.2 ms |
| kaiser | 49,721.069 Hz | 3,328 / 4,096 | 101.5625 MHz | 7,709 | 0.5 | -112.957 dBm | 112.7 ms |

## Detector measurements

Sample, positive-peak, average, negative-peak, and RMS were returned unchanged. Auto-peak (`7`) was accepted but returned as RMS (`6`). Across these rows, actual RBW remained 60,306.091 Hz, point count 3,328, span 101.5625 MHz, scale 0.5 dB/code, SDK rate approximately 7,703–7,707 traces/s, and reconfiguration approximately 110–113 ms.

## Integrated API acceptance

Nine consecutive owner-thread transactions (RBW manual/auto, window, detector, coercion, and safe restoration) completed without acquisition errors or rollback. Mean backend transaction time was 96.9 ms and the maximum was 109.7 ms. Manual 300 kHz read back as 241,224.365 Hz with 832 points/1,024 FFT; flat-top read back as flat-top with 115,058.899 Hz actual RBW; average read back unchanged; and auto-peak was coerced to RMS. The final state was restored to automatic RBW, Blackman–Nuttall, positive-peak, 3,328 points, and 101.5625 MHz span.

Reproduce safely with:

```bash
npm run backend:stop
python3 backend/tools/list_san90_rta_profiles.py \
  --duration 1 \
  --rbw-hz 15000 --rbw-hz 50000 --rbw-hz 300000 \
  --include-windows --include-detectors
```
