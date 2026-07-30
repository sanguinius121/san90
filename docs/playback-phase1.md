# SAN-90 Playback Phase 1

Last updated: 2026-07-29

Phase 1 replays clean application-owned `.san90rta` files through the existing
temporal-spectrum, waterfall, WebSocket, and browser renderer paths. It is not
compatible with SAStudio `.rtspectrum`.

## Architecture

```text
RecordingCatalog -> PlaybackIndex -> PlaybackEngine -> PlaybackSource
                                                       |-- temporal spectrum
                                                       `-- waterfall batches
```

`PlaybackIndex` scans headers sequentially and retains compact, slotted batch
descriptors containing record/payload offsets, dimensions, timing, CRC, and
CONFIG references. It reads small SESSION/CONFIG payloads but seek-skips native
trace payloads, so memory use is proportional to batch count. Open validates
file/record headers, type layouts, CONFIG-before-TRACE, sequence/GAP
continuity, END counters, and clean finalization. Because a fast open does not
read trace payloads, it cannot recompute the file rolling CRC without defeating
streaming indexing. Every trace payload is CRC32C-validated immediately before
publication. The independent inspection reader remains the full-file
validation tool.

Catalog IDs are the first 128 bits of SHA-256 over the safe relative path.
Resolution rescans the backend-owned recording root and matches the ID; client
paths are never accepted. Recursive listing skips symlinks, excludes `.part`,
does not expose absolute paths, and reports corrupt final files as
`playable=false`.

The playback worker uses recorded host-monotonic batch deltas at 1×. Pause
freezes the recorded position and Resume creates a new host-monotonic anchor.
Catch-up is capped at 50 ms to avoid downstream bursts. Completion waits for
the recorded END duration, leaving the final frame visible. Intra-batch trace
periods are passed to the existing vectorized aggregation paths; playback does
not emit one WebSocket message per native trace.

CONFIG is activated before its first TRACE. Center/frequency and amplitude
mapping changes update source state without a playback-specific renderer.
Point-count changes rebuild only source-side aggregation dimensions and flow
through the existing generation-aware frontend lifecycle. Native hardware
offset and software Amplitude Offset are combined exactly once at the
`RawAmplitudeMapping` conversion boundary.

GAP records are passed in record order. Reconfiguration pauses increment their
own counter and preserve recorded timing through subsequent batch timestamps;
they do not count as lost traces. Loss gaps do not synthesize data.

## Source arbitration and AI

The physical/simulator acquisition object remains alive and bounded while
playback exclusively owns display publication. Frequency Scan is stopped
before Open. Analyzer controls and recording start are rejected until Playback
Stop. Stop closes the worker/source and restores publication from the previous
source without applying recorded CONFIG values to hardware.

SAN-90 AI GRAY8 publication is disabled while playback is open and restored on
Stop. Current AI detections are cleared on Open and incoming port-5558 results
are suppressed until restoration. Playback traces are never sent to the AI
publisher.

## API

- `GET /api/analyzer/recordings`
- `GET /api/analyzer/recordings/{recording_id}`
- `GET /api/analyzer/playback/status`
- `POST /api/analyzer/playback/open` with `{"recording_id":"..."}`
- `POST /api/analyzer/playback/play`
- `POST /api/analyzer/playback/pause`
- `POST /api/analyzer/playback/stop`

Open transitions to READY and does not autoplay. COMPLETED requires Stop and
Open for another run. Stop is idempotent.

## 2026-07-29 hardware acceptance

The managed SAN-90 backend remained connected and acquiring during playback.

| Recording | Recorded | Playback wall time | CONFIG order | Pauses | Result |
|---|---:|---:|---|---:|---|
| Fixed | 5.0008 s | 5.0706 s active (plus 0.5 s paused) | 2.45 GHz | 0 | completed |
| Tune | 2.5016 s | 2.6181 s | 2.45, 2.44 GHz | 1 | completed |
| Scan | 2.8010 s | 2.9030 s | 2.45, 0.4, 0.9, 2.44 GHz | 3 | completed |

All runs published version-4 temporal spectrum and version-3 waterfall
messages. Fixed Pause held position at `2.001950869 s` for 500 ms. Tune and
scan playback reported zero lost traces. The physical center remained
2.45 GHz before and after every playback; acquisition errors and timeouts
remained `0 -> 0`. Stop restored SAN-90 publication and AI image creation.

The tune and scan fixtures were newly recorded because only one clean Fixed
recording remained on this machine. Their reader validation is clean, with one
and three explicit zero-loss `RECONFIGURATION_PAUSE` records respectively.

## Follow-on

Timeline seek, trace stepping, Auto Loop, playback AI rerun, and the full
Playback panel are implemented in `docs/playback-phase2.md`. Playback remains
fixed at 1×. `.part` recovery, sidecar indexes, and file download/delete remain
deferred.
