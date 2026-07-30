# SAN-90 Playback Phase 2

Last updated: 2026-07-29

Phase 2 keeps playback permanently fixed at real-time 1× and adds the complete
sidebar control surface, deterministic seek/step/loop behavior, and optional
AI rerun. There is no speed request, status field, setting, persistent value,
or frontend control.

## Controls and API

The Playback section appears immediately below Record. It lists only clean,
playable `.san90rta` files by opaque recording ID and opens a selection only
when the user presses Open. The compact controls are previous trace, back five
seconds, play/pause, forward five seconds, next trace, and Stop. A protected
seconds-based timeline sends one seek on release instead of polling while the
user drags. Auto Loop and Run AI are the only playback settings.

Phase 2 adds:

- `POST /api/analyzer/playback/seek` with `{"position_s": 2.5}`;
- `POST /api/analyzer/playback/step` with `{"direction":"previous"|"next"}`;
- `PUT /api/analyzer/playback/settings` with
  `{"auto_loop":false,"run_ai":false}`.

The settings request rejects extra fields, including `speed`. Active status is
polled every 250 ms; READY, PAUSED, COMPLETED, and IDLE use 750 ms.

## Timeline reset and epoch

Open, seek, step, each loop restart, Stop, and failure advance a monotonic
`playback_epoch`. Seek validates the absolute position, stops scheduled output,
clears temporal spectrum and waterfall exchanges, activates the target CONFIG,
CRC32C-validates the complete containing batch, publishes exactly the selected
trace, and ends PAUSED. Back/Forward clamp a frontend-computed target by five
seconds and use the same endpoint. Trace stepping traverses batch and CONFIG
boundaries without wrapping and also ends PAUSED.

Auto Loop resets the same state, advances epoch and loop count, and reuses the
already-open descriptor/index. It neither reopens the file nor remounts the
WebGL renderers. Point-count changes continue through the existing controlled
generation path.

## Playback AI correlation

Run AI defaults Off. When enabled, hardware/simulator AI input remains
suppressed and `PlaybackSource` feeds recorded native traces and CONFIG mapping
through the existing 640×640 GRAY8 accumulator and ZeroMQ port 5557. Cadence
stays at the configured 7–10 images/s. Manual trace steps deliberately do not
create AI images.

No port-5557 or port-5558 contract change was required. Future image sequences
are namespaced by playback epoch and reset counter. A bounded internal registry
maps the sequence echoed by the external detector to `(epoch, config_id)`.
Port-5558 results are published only when both still match the active playback
timeline. Seek, loop, CONFIG activation, Stop, and failure clear the registry
and broadcast an empty detection result, preventing stale annotations from
crossing frequency mappings. AI bind/inference failure is isolated from core
spectrum playback.

## 2026-07-29 acceptance

Focused automated results were 84 Python tests and 57 frontend tests passed;
the production frontend build and Python compile checks also passed.

The simulator API acceptance completed Open, step, seek, Run AI, Play, Pause,
and Stop; six playback images were sent before Pause and the simulator source
was restored.

Real SAN-90 acceptance used the existing Fixed, Tune, and Scan recordings:

- Fixed paused at 1.254 s, sought to 2.5 s, ended PAUSED at seek, then completed
  at 5.0008 s. Ten detections arrived before seek and 19 after; every post-seek
  result carried only the new epoch and `source=playback`.
- Tune activated 2.45 then 2.44 GHz.
- Scan activated the recorded initial CONFIG followed by 400, 400
  mapping-change, 900, and 2440 MHz; three pauses and zero lost traces passed.
- Auto Loop completed two restart boundaries without reopening the file; Stop
  returned IDLE in 28 ms.
- The WebSocket observer received 846 temporal-spectrum, 845 waterfall, and
  107 AI messages during the short acceptance.
- After Stop, the physical SAN-90 was still at 2.45 GHz, 3,328 points and
  60.306 kHz RBW. Hardware acquisition resumed near 5,085 trace/s with 60 FPS,
  AI output at 7 images/s, and acquisition errors/timeouts unchanged at zero.

## Deferred

File download/delete management, incomplete `.part` playback, sidecar indexes,
and playback rendering of reconstructed historical waterfall content remain
out of scope.

## Stop/restore generation correction

The browser generation guard is scoped to the active display source. When
status changes between SAN-90/simulator and playback, both the Web Worker and
main-thread receiver adopt the new source generation exactly instead of
retaining the numeric maximum from the previous source. This is required when,
for example, playback generation 2 yields to hardware generation 1. Sequence
and stale-generation protection remain monotonic within each source.

The 2026-07-29 regression acceptance sought the Tune recording onto playback
generation 2, stopped, received the SAN-90 restore status at generation 1, then
accepted 66 temporal-spectrum and 66 waterfall messages at hardware generation
1 during the following 1.1 seconds. Acquisition errors and timeouts remained
zero. The UI source indicator now distinguishes PLAYBACK from LIVE, and AI
tooltips identify Playback AI versus Realtime AI.

## Calibration-only CONFIG continuity

Native hardware calibration readback may change inside an otherwise fixed
recording. Two physical recordings reproduced such changes after 1.415 s and
2.077 s: center/start/stop frequency, point count, RBW, and analyzer generation
were unchanged, while `hardware_offset_dbm` moved by about 0.07 dB. These remain
valid CONFIG records for trace decoding, but are not display-geometry changes.

Playback now updates the active calibration and invalidates CONFIG-scoped AI
correlation without advancing the display generation or reconfiguring the
waterfall producer. Frequency-range or point-count changes still advance the
display generation and reset aligned history as required; explicit open,
seek, step, loop, and failure resets are unchanged. A replay through the
1.415-second transition retained one display generation and emitted 150
strictly increasing waterfall batches through 2.5 seconds.
