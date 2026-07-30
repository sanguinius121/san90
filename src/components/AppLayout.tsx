import { SpectrogramPanel } from "./SpectrogramPanel";
import { SpectrumPanel } from "./SpectrumPanel";
import { AiAnnotationStrip } from "./AiAnnotationStrip";
import { ToolRail, type DockPanel } from "./ToolRail";
import { ControlSidebar } from "./ControlSidebar";
import { useRef, useState } from "react";
import { useRuntimeStore } from "../stores";
import { RightDockSplitter } from "./layout/RightDockSplitter";
import { useResizableRightDock } from "../hooks/useResizableRightDock";
import { AiPreviewSidebar } from "./AiPreviewSidebar";

export function AppLayout() {
  const gridRef = useRef<HTMLElement>(null);
  const [dockPanel, setDockPanel] = useState<DockPanel>("rf");
  const rightDock = useResizableRightDock(gridRef);
  const runtime = useRuntimeStore();
  const {
    fps,
    waterfallFps,
    waterfallBatchFps,
    webglFps,
    spectrogramFps,
    droppedFrames: dropped,
    connection: state,
    source,
    pointCount,
    sdkFps,
    replacedSnapshots,
    tracesPerWaterfallRow,
  } = runtime;
  const selectSource = (value: string) => {
    const url = new URL(location.href);
    url.searchParams.set("source", value);
    location.assign(url);
  };
  const command = async (action: "start" | "stop" | "reconnect") => {
    try {
      const response = await fetch(
        `http://${location.hostname}:8000/api/analyzer/${action}`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(await response.text());
      useRuntimeStore
        .getState()
        .update({
          connection: action === "stop" ? "stopped" : "connected",
          lastError: undefined,
        });
    } catch (error) {
      useRuntimeStore
        .getState()
        .update({
          connection: "error",
          lastError:
            error instanceof Error ? error.message : "Analyzer command failed",
        });
    }
  };
  return (
    <div
      className="app-shell"
      data-spectrum-render-ms={runtime.spectrumRenderTimeMs}
      data-spectrogram-upload-ms={runtime.spectrogramUploadTimeMs}
      data-spectrogram-render-ms={runtime.spectrogramRenderTimeMs}
      data-pending-spectrum-merges={runtime.pendingSpectrumMerges}
      data-pending-waterfall-replacements={
        runtime.waterfallPendingBatchesReplaced
      }
      data-pending-waterfall-rows-replaced={
        runtime.waterfallPendingRowsReplaced
      }
      data-stale-batches={runtime.staleBatchesRejected}
      data-malformed-batches={runtime.malformedBatchesRejected}
      data-texture-wraps={runtime.textureWrapCount}
      data-valid-waterfall-rows={runtime.validWaterfallRows}
      data-waterfall-write-row={runtime.waterfallWriteRow}
      data-waterfall-visible-start-row={runtime.waterfallVisibleStartRow}
      data-waterfall-out-of-order={runtime.waterfallOutOfOrderBatches}
      data-waterfall-sequence-gaps={runtime.waterfallSequenceGaps}
    >
      <header className="app-header">
        <div className="product">
          <span className="product-mark">S90</span>
          <div>
            <b>SPECTRUM CONSOLE</b>
            <small>REAL-TIME RF ANALYSIS</small>
          </div>
        </div>
        <div className="session">
          <span className={`status-indicator ${state}`} />
          <b>
            {source === "simulator"
              ? "SIMULATED INPUT"
              : state === "connected"
                ? "SAN-90 CONNECTED"
                : `SAN-90 ${state.toUpperCase()}`}
          </b>
          <select
            aria-label="Input source"
            value={source}
            onChange={(event) => selectSource(event.target.value)}
          >
            <option value="simulator">Simulator</option>
            <option value="san90">SAN-90</option>
          </select>
          <i>{pointCount} PTS</i>
          <i>
            S {fps} / W {waterfallFps} ROW/s
          </i>
          <i>
            GL S {webglFps} / W {spectrogramFps} FPS
          </i>
          <i>{waterfallBatchFps} BATCH/s</i>
          {source === "san90" && (
            <>
              <i>{sdkFps.toFixed(0)} SDK FPS</i>
              {tracesPerWaterfallRow != null && (
                <i>{tracesPerWaterfallRow.toFixed(1)} TRACE/ROW</i>
              )}
              <i>{replacedSnapshots} REPLACED</i>
              <button
                onClick={() => command(state === "stopped" ? "start" : "stop")}
              >
                {state === "stopped" ? "START" : "STOP"}
              </button>
              <button onClick={() => command("reconnect")}>RECONNECT</button>
            </>
          )}
          <i>{dropped} INVALID</i>
        </div>
        <time>
          {new Date().toLocaleDateString(undefined, {
            day: "2-digit",
            month: "short",
            year: "numeric",
          })}
        </time>
      </header>
      <main className="app-grid" ref={gridRef}>
        <div className="measurement-area">
          <SpectrogramPanel />
          <AiAnnotationStrip />
          <SpectrumPanel />
        </div>
        <RightDockSplitter
          width={rightDock.width}
          limits={rightDock.limits}
          onBeginDrag={rightDock.beginDrag}
          onMoveDrag={rightDock.moveDrag}
          onEndDrag={rightDock.endDrag}
          onCancelDrag={rightDock.cancelDrag}
          onResizeBy={rightDock.resizeBy}
          onMinimum={rightDock.setToMinimum}
          onMaximum={rightDock.setToMaximum}
        />
        <div className="right-dock">
          <ToolRail panel={dockPanel} onPanelChange={setDockPanel} />
          {dockPanel === "rf"
            ? <ControlSidebar onResetLayout={rightDock.reset} />
            : <AiPreviewSidebar onResetLayout={rightDock.reset} />}
        </div>
      </main>
    </div>
  );
}
