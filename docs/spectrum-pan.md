# Spectrum Pan

Implemented and validated: 2026-07-31.

## Interaction

The `Pan` entry in the analysis rail is frontend interaction state only:

```text
OFF → ARMED → DRAGGING → TUNING → ARMED
```

Pointer down is accepted only inside `sharedHorizontalPlotRect()`. The drag
captures the verified packet center/span, plot width, pointer ID, and
configuration generation. Pointer movement is animation-frame throttled and
does not update analyzer state or call the backend.

The target mapping is:

```text
targetCenterHz =
startCenterHz - (deltaX / plotWidthPx) * actualSpanHz
```

The preview is clamped so both span edges remain inside the device frequency
limits. Release requires at least 4 px and one frequency pixel of movement.
The final request is rounded to integer Hz.

## Rendering and confirmation

`SpectrumRenderer` keeps its existing WebGL context, shader program, buffers,
frame subscription, and animation loop. A `panOffsetClip` uniform translates
the current and interval-maximum traces. The existing full clear plus plot
viewport clipping exposes the normal black plot background on the uncovered
side and prevents trace drawing over axes or adjacent UI.

Only the Spectrum frequency axis uses the temporary preview center.
Spectrogram data and mapping remain verified and continue updating during the
drag. Marker labels and the AI annotation strip are suppressed during drag.
At release the final translated trace is dimmed, stale detections are cleared,
and `TUNING` remains active until a Spectrum packet matches both the verified
readback center and returned configuration generation. HTTP success alone
does not complete Pan.

The Center Frequency input and Pan call the same
`commitCenterFrequencyHz()` action. SAN-90 uses the existing
`PUT /api/analyzer/frequency` transaction. The in-browser simulator advances
one configuration generation through the same action. Playback, Frequency
Scan, disconnected, and externally reconfiguring states disable Pan.

The existing spectrogram generation transition is the only renewal path:
same-size generation changes clear the current texture and cursor once;
point-count changes use the existing controlled reallocation. Old queued rows
are discarded by the generation-aware bounded batch buffer. The configured
visible interval remains 5.0 seconds.

## Validation

Focused automated validation covered mapping direction, plot-width use,
span-aware clamps, threshold behavior, RAF throttling, no request during
pointer movement, exactly one release commit, packet-based completion,
failure/cancel/Escape behavior, scan/playback exclusion, renderer lifecycle,
same-size texture reuse, point-count reallocation, and the shared Center
Frequency control path.

Simulator backend acceptance:

- 2.450000000 GHz → 2.460156250 GHz for a 10% left-pan equivalent;
- generation `1 → 2`;
- Spectrum/Waterfall `60/60` publications per second;
- visible spectrogram duration `5.0 s`;
- acquisition error and timeout deltas `0/0`.

Real SAN-90 acceptance at 3,328 points, 60.306091 kHz RBW, 101.5625 MHz span:

- left-pan equivalent: 2.450000000 → 2.460156250 GHz, request 115.53 ms;
- right-pan equivalent: 2.450000000 → 2.439843750 GHz, request 116.10 ms;
- both paths returned verified readback and one generation increment;
- browser held a -80 px drag for one second with center unchanged, while valid
  spectrogram rows advanced from 121 to 182;
- release produced one tune and generation `8 → 9`; Escape produced no tune;
- Spectrum canvas identity remained unchanged and WebSocket reconnect delta
  was zero;
- a five-second recording contained exactly two CONFIG records and one
  zero-loss reconfiguration GAP, with no rejected batches;
- playback and Frequency Scan both rejected manual tune attempts while active;
- final center was restored to 2.45 GHz;
- Spectrum/Waterfall recovered to `60/60`;
- acquisition error and timeout deltas remained `0/0`.

The browser acceptance was run headlessly through Firefox/WebDriver. The
WebGL translation/clipping behavior is covered structurally and by focused
tests; a human visual check of the uncovered black side remains useful when
the operator next opens the UI.
