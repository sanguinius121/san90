# Resizable right dock and AI image preview

Status: implemented and focused-test verified on 2026-07-30. The resize path
was manually checked with the simulator and physical SAN-90. The preview path
was checked with the simulator, physical SAN-90, and fixed-file playback.

## Resizable right dock

The desktop layout is:

```text
measurement | 6 px splitter | right dock
                              navigation | controls
```

The right dock includes the fixed-width navigation rail and control sidebar.
Its width defaults to 418 px, is clamped to 398–778 px, and is further limited
so the measurement area retains at least 640 px. Navigation remains 78 px in
the normal desktop layout. The existing vertical measurement rows are
unchanged; only their CSS width changes.

`useResizableRightDock` writes `--right-dock-width` directly on the layout
element. Pointer movement is coalesced to one update per animation frame and
React state/local storage are updated only on commit. The persisted key is
`san90.layout.rightDockWidth`. `Reset layout` removes it and restores 418 px.

The splitter is a keyboard-focusable vertical ARIA separator:

- Left/Right change the dock by +10/-10 px.
- Shift uses a 50 px step.
- Home and End select the current minimum and maximum.
- Pointer cancellation or Escape during a drag restores its starting width.

Neither plot receives the dock width as a React key or renderer lifecycle
dependency. ResizeObserver changes canvas backing dimensions and WebGL
viewports in place. It does not recreate the WebGL contexts, programs,
buffers, or spectrogram texture, and it does not clear waterfall history.
The visible spectrogram interval remains 5.0 seconds.

## AI image preview

The existing AI publisher normalizes each completed image once to the exact
640×640 GRAY8 array used by the port-5557 message. The same array is offered to
a separate latest-only preview encoder. No image is reconstructed from browser
spectrum data.

The preview encoder:

- runs on `san90-ai-preview`, not the SAN-90 owner thread;
- owns one immutable 409,600-byte GRAY8 copy for each accepted preview;
- has a queue capacity of one and replaces stale pending work;
- is limited to 2 PNG images/s independently of the normal 7–10 AI images/s;
- copies and encodes only while a visible frontend renews a 1.5-second
  viewer lease;
- stores only one immutable encoded PNG and its matching metadata;
- uses a reset token so an encode started before seek, loop, CONFIG change,
  source restore, disable, or failure cannot republish stale content.

Preview encoding is lossless grayscale PNG using Pillow with compression
level 3. During the short physical run, observed encoding latency was about
11.5 ms/image while SAN-90 acquisition remained near 5,086 native traces/s
and spectrum/waterfall publication stayed 60/60. With no viewer, zero images
were copied or encoded over an eight-second sample. With a viewer, 20 images
were encoded in ten seconds, the encoder used about 1.9% of one CPU core, and
PNG traffic was about 544 kB/s. After lease expiry, the encoded counter again
remained unchanged.

The API is:

```text
GET /api/analyzer/ai/preview/status
GET /api/analyzer/ai/preview/image?sequence=<latest sequence>
```

Status reports source (`hardware`, `simulator`, or `playback`), sequence,
playback epoch, config ID, analyzer generation, frequency bounds, dimensions,
and creation time. Image retrieval succeeds only for the exact current
sequence; an old/new mismatch returns 404. Both responses use no-cache
headers.

The navigation rail has separate `RF` and `AI Preview` destinations. `RF`
shows the eight analyzer sections; `AI Preview` replaces that sidebar content
with only the latest-image panel. While the AI panel is selected and the page
is visible it polls status every 250 ms and renews the backend viewer lease,
fetching an image only when sequence changes. Navigating back to RF unmounts
the preview. Hidden-page polling is reduced to 1 second without renewing the
lease. After navigation, unmount, or page hiding, encoding stops no later than
the lease timeout. It uses a single Blob URL, revokes the prior URL on
replacement and the final URL on unmount, and uses CSS
`aspect-ratio: 1 / 1` plus `object-fit: contain`. Changing dock width does not
fetch or recreate the image.

Playback reuses the existing playback AI pipeline. Preview source, epoch, and
CONFIG metadata are captured with the image. Playback Open, seek, step, loop,
CONFIG activation, Stop, failure, and source restoration clear or invalidate
the preview. When playback Run AI is disabled, status reports
`playback_ai_disabled`. After Stop, a playback PNG cannot remain visible; the
store waits for a newly completed hardware/simulator image.

The ZeroMQ port-5557 and port-5558 contracts are unchanged.

## Verification

Focused automated verification:

```text
29 frontend layout/preview/lifecycle/sidebar tests passed
42 backend preview/AI/playback/integration tests passed
TypeScript project check passed
Python compile check passed
```

Manual simulator resize held the preview square while the spectrogram row/write
indexes continued forward. Physical SAN-90 resize for about 10 seconds observed
60/60 spectrum/waterfall publication, WebGL 58/60 FPS, zero invalid frames,
zero acquisition errors/timeouts, zero WebSocket reconnects, and advancing
spectrogram history. The physical preview decoded as 640×640 PNG.

A fixed hardware recording was opened with playback AI, played, sought, and
stopped. Seek changed epoch 1→2 and immediately cleared the old preview; the
new PNG carried epoch 2/config 2. Stop restored live SAN-90 acquisition and a
fresh HARDWARE preview with errors/timeouts unchanged at zero. No physical
configuration transaction occurred during playback.

End-to-end YOLO cadence could not be rechecked in this task because the
user-modified nested detector currently has a Python syntax error at
`yolo_detection.py:180`. The backend correctly continued with bounded
non-blocking port-5557 drops, and preview production remained independent.
Tune/scan preview playback was not repeated because the two available clean
recordings contain only the 2.45 GHz range.
