# Spectrogram continuity and shared-axis validation

Validated on 2026-07-20 with the managed SAN-90 backend, HTRA API 0.55.88, and the hardware-accelerated Firefox/WebGL2 frontend.

## Root cause and correction

The horizontal boundary was a vertical viewport-mapping defect, not an RF discontinuity and not a backend trace-order defect. At the minimum-RBW profile the five-second viewport contains 300 source rows, while the captured plot was approximately 442 pixels high. The old fragment shader calculated:

```text
rows_per_pixel = max(1, visible_rows / output_height)
age = min(visible_rows, 1 + floor(output_y * rows_per_pixel))
```

This forced `rows_per_pixel` to one. Output pixels 0 through 299 displayed the 300 chronological rows, but every remaining output pixel repeated the oldest row. The visual transition therefore occurred at `300 / 442 * 5 = 3.39 seconds`, close to the reported seam. It appeared only at 60.306 kHz because that profile has only 300 visible rows; profiles with more source rows did not enter the same clamped-upsampling case.

The shader now defines one source interval for every output row over the complete chronological viewport:

```text
source_start = output_y * visible_rows / output_height
source_end = (output_y + 1) * visible_rows / output_height
source ages = floor(source_start) .. ceil(source_end) - 1
texture_row(age) = (write_row - 1 - age + texture_rows) mod texture_rows
output = maximum(all source rows in the interval)
```

This mapping neither restarts nor changes its sampling policy at the physical texture boundary. When the viewport is taller than its history, chronological rows are evenly expanded over the full five-second plot. When history is denser than the plot, each pixel max-preserves every source row in its interval, including intervals crossing texture row zero.

`CircularWaterfallCursor` now separates upload planning from commit. A wrapping batch uploads its tail at the end of the texture, then its head at row zero, and advances `write_row` only after both uploads complete. `valid_row_count` starts at zero and resets on a point-count/configuration change, so zero-initialized but unwritten rows are never treated as history. The live path also records receive-order gaps, reversed batches, bounded-buffer ordering, valid rows, write row, and visible start row. `?source=san90&waterfallDebug=rows` replaces amplitude rows with a row-sequence color code for visual ordering diagnosis.

## Live circular-wrap result

The minimum-RBW profile was left running through an actual 4,096-row texture wrap. At capture time:

| Metric | Result |
|---|---:|
| Actual RBW | 60.306091 kHz |
| Points / FFT | 3,328 / 4,096 |
| SDK acquisition | approximately 7,629 traces/s |
| Waterfall | 60 rows/s, 60-61 batches/s, 1 row/batch |
| Texture wraps | 1 |
| Valid texture rows | 4,096 |
| Write row | 2,718 |
| Visible start row | 2,418 |
| Visible rows / span | 300 / 5.0 s |
| Receive-order errors | 0 |
| Row/batch sequence gaps | 0 |
| Replaced waterfall batches/rows | 0 / 0 |
| Stale/malformed batches | 0 / 0 |

The before image is the screenshot attached to the defect report. The post-fix, post-wrap capture is [spectrogram-continuity-after.png](screenshots/spectrogram-continuity-after.png). It shows continuous texture through the entire five-second interval and aligned major grid lines in the two panels.

## Shared plot rectangle

Both panels now obtain horizontal CSS geometry from `sharedHorizontalPlotRect()`:

```text
plot_left_css_px = 48
plot_right_css_px = canvas_css_width - 10
plot_width_css_px = plot_right_css_px - plot_left_css_px
x = plot_left_css_px
  + (frequency_hz - start_frequency_hz)
  / (stop_frequency_hz - start_frequency_hz)
  * plot_width_css_px
```

Spectrum WebGL, spectrogram WebGL, both Canvas 2D frequency axes, marker placement, cursor anchoring, zoom, and pan use this shared rectangle. The CSS rectangle is converted to framebuffer pixels only at the WebGL viewport boundary. Tests cover DPR 1 and 2 and width changes; CSS-frequency mapping never uses drawing-buffer width.

In the live 1,600-pixel browser capture both plot stages were 1,181 CSS pixels wide and both resolved to `{left: 48, right: 1171, width: 1123}`. Major ticks and their vertical grid lines occupy identical screen X coordinates.

## Eight-profile regression

All eight manual profiles were applied through the running owner-thread backend and matched their requested indices:

| Index | Actual RBW | Points / FFT | Observed SDK traces/s | Waterfall rows/s | Rows/batch |
|---:|---:|---:|---:|---:|---:|
| 0 | 7.719180 MHz | 26 / 32 | 975,495 | 480 | 8 |
| 1 | 3.859590 MHz | 52 / 64 | 487,263 | 480 | 8 |
| 2 | 1.929795 MHz | 104 / 128 | 243,609 | 480 | 8 |
| 3 | 964.897 kHz | 208 / 256 | 121,808 | 480 | 8 |
| 4 | 482.449 kHz | 416 / 512 | 60,832 | 480 | 8 |
| 5 | 241.224 kHz | 832 / 1,024 | 30,455 | 240 | 4 |
| 6 | 120.612 kHz | 1,664 / 2,048 | 15,220 | 120 | 2 |
| 7 | 60.306 kHz | 3,328 / 4,096 | 7,618 | 60 | 1 |

Spectrum publication remained configured at 60 FPS and waterfall batching remained 60 batches/s. The live GPU capture sampled spectrum/spectrogram rendering at 54-60/58-60 FPS while a second diagnostic browser was attached; sampled render costs were approximately 0.09 ms for spectrum, 0.02 ms for waterfall upload, and below 0.14 ms for the spectrogram draw. The established single-browser baseline remains 59-60 FPS. No unbounded queue, stale generation, malformed frame, waterfall replacement, or acquisition-rate reduction was observed.

The long-running managed backend used 97.1 MiB RSS. A two-second sample with one WebSocket browser attached measured 54% of one CPU core at index 6. This is not directly comparable with the earlier direct-acquisition baseline (which excluded the live WebSocket/browser workload); the current changes are frontend-only and add no backend processing. Renderer timing stayed well below the 16.67 ms frame budget.

The pre-test manual profile (index 6, 120.612 kHz) was restored after the eight-profile run. The existing managed backend and frontend were left running as they were found.

## Tests and build

New coverage includes one-, four-, and eight-row upload wraps; multiple queued wraps; strict chronological texture order; duplicate/reversed batch rejection; generation reset; valid-row reset; a 300-row/five-second viewport over 442 output pixels; a max-pool interval crossing row zero; debug row encoding; shared plot edges; start/center/stop mapping; marker/cursor mapping; resize; and DPR 1/2 framebuffer conversion.

Commands run:

```bash
python3 -m unittest discover -s tests -v
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm test
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm run lint
PATH=/home/tuancoi/.local/nodejs/node-v22.17.0-linux-x64/bin:$PATH npm run build
```

Results: 62 Python tests passed; 58 TypeScript tests passed; ESLint passed; production TypeScript/Vite build passed.
