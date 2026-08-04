import { SpectrogramPanel } from "./SpectrogramPanel";
import { SpectrumPanel } from "./SpectrumPanel";
import { AiAnnotationStrip } from "./AiAnnotationStrip";
import { ToolRail, type DockPanel } from "./ToolRail";
import { ControlSidebar } from "./ControlSidebar";
import { useEffect, useRef, useState } from "react";
import { useRuntimeStore, useUiPreferencesStore } from "../stores";
import { RightDockSplitter } from "./layout/RightDockSplitter";
import { useResizableRightDock } from "../hooks/useResizableRightDock";
import { AiPreviewSidebar } from "./AiPreviewSidebar";
import { formatHeaderDateTime } from "../utils/format";
import type { UiLanguage } from "../data/uiLanguage";

export function AppLayout() {
  const gridRef = useRef<HTMLElement>(null);
  const [dockPanel, setDockPanel] = useState<DockPanel>("rf");
  const [now,setNow]=useState(()=>new Date())
  const language=useUiPreferencesStore((state)=>state.language)
  const setLanguage=useUiPreferencesStore((state)=>state.setLanguage)
  const rightDock = useResizableRightDock(gridRef);
  const runtime = useRuntimeStore();
  const {
    connection: state,
    source,
    spectrogramFps,
    tracesPerWaterfallRow,
  } = runtime;
  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(new Date()),1000)
    return ()=>window.clearInterval(timer)
  },[])
  useEffect(()=>{
    document.documentElement.lang=language
  },[language])
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
          <span className="product-mark">PTL-26</span>
          <div className="product-title">
            <b>GIÁM SÁT VÔ TUYẾN</b>
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
          {source === "san90" && (
            <>
              <i className="session-primary-metric">{spectrogramFps.toFixed(0)} SPECTROGRAM FPS</i>
              {tracesPerWaterfallRow != null && (
                <i className="session-primary-metric">{tracesPerWaterfallRow.toFixed(1)} TRACE/ROW</i>
              )}
              <button
                onClick={() => command(state === "stopped" ? "start" : "stop")}
              >
                {state === "stopped" ? "START" : "DỪNG"}
              </button>
              <button onClick={() => command("reconnect")}>KẾT NỐI LẠI</button>
            </>
          )}
        </div>
        <div className="header-language">
          <label htmlFor="ui-language">Ngôn ngữ/Language</label>
          <select
            id="ui-language"
            value={language}
            onChange={(event)=>setLanguage(event.target.value as UiLanguage)}
          >
            <option value="en">ENG</option>
            <option value="vi">VIỆT</option>
          </select>
        </div>
        <time dateTime={now.toISOString()}>{formatHeaderDateTime(now)}</time>
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
