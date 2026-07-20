# Fixed-rate temporal display pipeline — Subphase A

Subphase A is complete in simulator mode. The SAN-90 was not opened and its owner-thread acquisition path was not connected to the new temporal spectrum protocol.

## Implemented policy

- Spectrum publication: fixed 60 messages/s for every resolution step.
- Spectrum WebGL target: fixed 60 FPS.
- Waterfall production remains capability-driven at 60, 120, 240, or 480 rows/s in 60 batches/s.
- Visible spectrogram duration remains 5 seconds; its newest 300–2,400 rows are sampled from a 4,096-row circular texture.
- A spectrum interval carries both the newest trace and an element-wise interval maximum. The simulator accumulates all generated native traces in reusable `uint8` buffers before converting the two display arrays to float32.
- Pending spectrum replacement is newest-only and merges maxima. Pending waterfall storage is capped at two batches; a replaced compatible batch is merged by maximum.

## Protocol and rendering

Version 4 message `0x02` uses a 128-byte header and two contiguous float32 arrays. Version 2 current-spectrum and version 3 batched-waterfall messages remain accepted. The Web Worker validates dimensions, interval timestamps, metadata, generation, and payload size, then transfers both array buffers.

The yellow line is the newest trace. The cyan line is the 60 Hz interval maximum and follows the existing persistence toggle, which remains enabled by default. Vertical waterfall reduction maps all source rows contributing to an output pixel and chooses their maximum. The data texture uses nearest sampling so interpolation cannot attenuate a short peak.

## Simulator validation

Both Python and browser simulators create a hop lasting one native trace, shorter than a 16.67 ms display interval. Tests verify that it is absent from the newest trace but present in the interval maximum. Dynamic point counts and waterfall batches remain supported.

## Verification

```bash
python3 -m unittest discover -s tests -v
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm test -- --run
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm run build
```

Results on 2026-07-20: 57 Python tests passed, 35 TypeScript tests passed, lint passed, and the production build completed.

## Subsequent SAN-90 integration

The later eight-profile milestone connected this interface to the real owner thread. Subphase B increased the frontend's bounded waterfall burst capacity from two to sixteen batches after GPU testing exposed burst replacements; it remains finite and drains chronologically. Hardware, GPU, lifecycle, and stability results are recorded in `san90-resolution-tradeoff-report.md`. This document remains the simulator-only Subphase A record.
