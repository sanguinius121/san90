import { useEffect, useRef, useState } from "react";
import { ColorScale } from "./ColorScale";
import { liveFrames } from "../data/liveFrames";
import {
  BoundedWaterfallBatchBuffer,
  SpectrogramRenderer,
} from "../rendering/SpectrogramRenderer";
import { resizeCanvas } from "../rendering/webgl";
import { useDeviceStore, useDisplayStore, useRuntimeStore } from "../stores";
import { FrequencyAxis } from "./FrequencyAxis";
import {
  waterfallHistorySeconds,
  waterfallVisibleRows,
} from "../rendering/SpectrogramRenderer";
import {
  FIXED_RENDER_PERIOD_MS,
  fixedRenderDecision,
} from "../rendering/renderSchedule";
import {
  sharedHorizontalPlotRect,
  visibleFrequencyPlotRange,
  type FrequencyPlotRange,
} from "../rendering/plotGeometry";

const centerFrequencyRange=(centerHz:number,spanHz:number):FrequencyPlotRange=>({
  startHz:centerHz-spanHz/2,
  stopHz:centerHz+spanHz/2,
})

export function SpectrogramPanel() {
  const glRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const overlayDirty=useRef(true)
  const [error, setError] = useState<string>();
  const center = useDeviceStore((s) => s.centerHz);
  const span = useDeviceStore((s) => s.spanHz);
  const frequencyRange=useRef(centerFrequencyRange(center,span))
  useEffect(()=>{
    frequencyRange.current=centerFrequencyRange(center,span)
    overlayDirty.current=true
  },[center,span])
  useEffect(() => {
    const canvas = glRef.current;
    const overlay = overlayRef.current;
    if (!canvas || !overlay) return;
    let renderer: SpectrogramRenderer;
    try {
      renderer = new SpectrogramRenderer(canvas,4096,new URLSearchParams(location.search).get("waterfallDebug")==="rows");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Spectrogram failed";
      const timer = window.setTimeout(() => setError(message), 0);
      return () => window.clearTimeout(timer);
    }
    let raf = 0;
    let dirty = true;
    let uploadedRows = 0;
    let uploadedAt = performance.now();
    let rendered = 0;
    let uploadTimeMs = 0;
    let renderTimeMs = 0;
    {
      const runtime = useRuntimeStore.getState();
      useRuntimeStore
        .getState()
        .update({
          waterfallTextureRows: renderer.textureRowCount,
          waterfallHistorySeconds: waterfallHistorySeconds(
            renderer.textureRowCount,
            runtime.waterfallRowsPerSecond,
          ),
          visibleWaterfallRows: waterfallVisibleRows(
            runtime.waterfallRowsPerSecond,
            runtime.visibleTimeSpanSeconds,
          ),
        });
    }
    const pending = new BoundedWaterfallBatchBuffer();
    const unsubscribe = liveFrames.subscribeWaterfall((frame) => {
      pending.push(frame);
      frequencyRange.current={startHz:frame.startHz,stopHz:frame.stopHz}
      overlayDirty.current=true
      dirty = true;
    });
    const drawOverlay = () => {
      resizeCanvas(overlay);
      const ctx = overlay.getContext("2d");
      if (!ctx) return;
      const dpr = overlay.width / overlay.clientWidth;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const w = overlay.clientWidth;
      const h = overlay.clientHeight;
      ctx.clearRect(0, 0, w, h);
      const horizontal=sharedHorizontalPlotRect(w)
      const area = { ...horizontal, top: 4, bottom: h - 26 };
      ctx.strokeStyle = "rgba(142,161,176,.18)";
      for (let i = 1; i < 6; i++) {
        const y = area.top + ((area.bottom - area.top) * i) / 6;
        ctx.beginPath();
        ctx.moveTo(area.left, y);
        ctx.lineTo(area.right, y);
        ctx.stroke();
      }
      const view = useDisplayStore.getState().viewport;
      const visible=visibleFrequencyPlotRange(frequencyRange.current,view)
      FrequencyAxis(
        ctx,
        area,
        visible.startHz,
        visible.stopHz,
      );
      const visibleSeconds = useRuntimeStore.getState().visibleTimeSpanSeconds;
      ctx.fillStyle = "#91a4b3";
      ctx.font = "10px Inter,system-ui";
      ctx.textAlign = "left";
      ctx.fillText(`-${visibleSeconds.toFixed(0)} s`, 12, 9);
      ctx.fillText("NOW", 12, area.bottom - 13);
      for (let second = 1; second < visibleSeconds; second++) {
        const y =
          area.bottom - ((area.bottom - area.top) * second) / visibleSeconds;
        ctx.fillText(`-${second} s`, 12, y);
      }
    };
    let nextRenderDeadline = 0;
    const animate = (now: number) => {
      const runtime = useRuntimeStore.getState();
      const hasHistory=renderer.validRowCount>0
      const decision =
        pending.size > 0
          ? { due: true, nextDeadline: now + FIXED_RENDER_PERIOD_MS }
          : hasHistory || dirty || overlayDirty.current
            ? fixedRenderDecision(now, nextRenderDeadline)
            : { due: false, nextDeadline: nextRenderDeadline };
      nextRenderDeadline = decision.nextDeadline;
      if (decision.due) {
        const uploadStarted = performance.now();
        for (const frame of pending.drain()) {
          renderer.addRows(
            frame.values,
            frame.rowCount,
            frame.pointCount,
            frame.firstRowSequence,
            frame.configurationGeneration,
          );
          uploadedRows += frame.rowCount;
        }
        uploadTimeMs += performance.now() - uploadStarted;
        if(renderer.validRowCount>0){
          resizeCanvas(canvas);
          const visible = waterfallVisibleRows(
            runtime.waterfallRowsPerSecond,
            runtime.visibleTimeSpanSeconds,
          );
          const renderStarted = performance.now();
          renderer.render(useDisplayStore.getState().viewport, visible);
          renderTimeMs += performance.now() - renderStarted;
          rendered++;
        }
        if (overlayDirty.current) {
          drawOverlay();
          overlayDirty.current = false;
        }
        dirty = false;
      }
      if (now - uploadedAt >= 1000) {
        const elapsed = (now - uploadedAt) / 1000;
        runtime.update({
          waterfallRowsUploadedFps: Math.round(uploadedRows / elapsed),
          spectrogramFps: Math.round(rendered / elapsed),
          spectrogramUploadTimeMs: rendered ? uploadTimeMs / rendered : 0,
          spectrogramRenderTimeMs: rendered ? renderTimeMs / rendered : 0,
            waterfallPendingBatchesReplaced: pending.replacedBatches,
            waterfallPendingRowsReplaced: pending.replacedRows,
          textureWrapCount: renderer.wrapCount,
          waterfallTextureRows: renderer.textureRowCount,
          waterfallHistorySeconds: waterfallHistorySeconds(
            renderer.textureRowCount,
            runtime.waterfallRowsPerSecond,
          ),
          visibleWaterfallRows: waterfallVisibleRows(
            runtime.waterfallRowsPerSecond,
            runtime.visibleTimeSpanSeconds,
          ),
          validWaterfallRows:renderer.validRowCount,
          waterfallWriteRow:renderer.writeRow,
          waterfallVisibleStartRow:renderer.validRowCount?((renderer.writeRow-Math.min(renderer.validRowCount,waterfallVisibleRows(runtime.waterfallRowsPerSecond,runtime.visibleTimeSpanSeconds))+renderer.textureRowCount)%renderer.textureRowCount):renderer.writeRow,
          waterfallOutOfOrderBatches:pending.outOfOrderBatches,
          waterfallOutOfOrderRows:pending.outOfOrderRows,
        });
        uploadedRows = 0;
        rendered = 0;
        uploadTimeMs = 0;
        renderTimeMs = 0;
        uploadedAt = now;
      }
      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    const observer = new ResizeObserver(() => {
      dirty = true;
      overlayDirty.current = true;
    });
    observer.observe(canvas);
    const unsubStore = useDisplayStore.subscribe(() => {
      dirty = true;
      overlayDirty.current = true;
    });
    return () => {
      unsubscribe();
      unsubStore();
      pending.clear();
      cancelAnimationFrame(raf);
      observer.disconnect();
      renderer.dispose();
    };
  }, []);
  return (
    <section className="plot-panel spectrogram-panel">
      <header className="plot-header">
        <div>
          <span className="plot-title">SPECTROGRAM</span>
          <span className="plot-subtitle">REAL-TIME WATERFALL</span>
        </div>
        <ColorScale />
      </header>
      <div className="plot-stage">
        <canvas ref={glRef} />
        <canvas className="overlay-canvas" ref={overlayRef} />
        {error && <div className="plot-error">{error}</div>}
      </div>
    </section>
  );
}
