# Batched waterfall pipeline — Subphase A

Subphase A implements and software-validates the batch contract without changing or opening SAN-90 hardware. The physical source continues producing the existing version-2 single-row waterfall until Subphase B.

## Design

- Spectrum remains an independent version-2 float32 message targeted at 60 messages/s.
- The simulator integrates every native trace in monotonic-time windows using max-hold in contiguous `uint8` storage.
- Completed rows fill one reusable two-dimensional NumPy staging array.
- A full batch is copied once into an immutable, contiguous `WaterfallBatch` and offered to a one-slot newest-data-first exchange.
- An unread batch may be replaced; replaced batches and rows are counted. No unbounded queue exists.
- Simulator defaults are profile-aware: 60 rows/s, 60 batches/s, one row/batch for the normal profile; 240 rows/s, 60 batches/s, four rows/batch for the simulated fast profile.
- Explicit environment values are rejected unless `rows/s = batches/s × rows/batch`.

## Protocol and browser path

Version-2 spectrum/status messages are unchanged. Version 3 is restricted to `0x03` waterfall batches and uses a 120-byte header followed by row-major `uint8[row_count][point_count]`. The worker accepts both the new format and legacy version-2 rows, validates dimensions and generation, and transfers the underlying payload buffer without per-row copies.

The WebGL2 renderer allocates 2,048 history rows. It uploads a normal batch with one `texSubImage2D`; a circular-boundary batch uses exactly two ordered uploads. One pending batch is consumed per animation frame, so the target remains 60 WebGL renders/s. With this texture depth, visible history is approximately 34.13 seconds at 60 rows/s and 8.53 seconds at 240 rows/s.

## Simulator acceptance measurement

A three-second in-process WebSocket-mailbox measurement of the simulated fast profile produced:

| Metric | Result |
|---|---:|
| Producer rows/s | 239.90 |
| Producer batches/s | 59.97 |
| Spectrum messages/s | 60.32 |
| Observed batch messages/s | 60.32 |
| Observed rows/s | 241.28 |
| Rows per batch | 4 |
| Protocol version | 3 |
| Missed deadlines / empty rows | 0 / 0 |
| Replaced producer batches | 0 |
| Mean simulated native traces/row | 4.00 |
| Waterfall wire bytes/s at 512 simulated fast points | 130,775 |
| Maximum resident set observed | 35.5 MiB |

The short measurement includes boundary effects in observed mailbox rates. Hardware trace integration near 127 traces/row, 832-point wire rate, browser render FPS, ten-minute memory stability, and FHSS visual comparison belong to Subphase B.

## Reproduction

```bash
python3 -m unittest discover -s tests -v

export NODE_BIN_DIR=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin
export PATH="$NODE_BIN_DIR:$PATH"
npm test
npm run lint
npm run build
```

To run the simulator backend explicitly at 240 rows/s:

```bash
SAN90_WATERFALL_ROWS_PER_SECOND=240 \
SAN90_WATERFALL_BATCHES_PER_SECOND=60 \
SAN90_WATERFALL_ROWS_PER_BATCH=4 \
npm run backend:start:simulator
```

## Deferred to Subphase B

- SAN-90 owner-thread row production and batch exchange integration
- safe/fast physical profile switching policy
- hardware row timing, trace-count, CPU, wire-rate, and acquisition-regression measurements
- browser/GPU profiling and ten-minute stability run with the physical analyzer
- hardware shutdown/reopen and safe-profile restoration acceptance
