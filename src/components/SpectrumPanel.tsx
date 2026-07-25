import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type WheelEvent,
} from "react";
import { liveFrames } from "../data/liveFrames";
import { SpectrumRenderer } from "../rendering/SpectrumRenderer";
import { resizeCanvas } from "../rendering/webgl";
import { useDeviceStore, useDisplayStore, useRuntimeStore } from "../stores";
import { FrequencyAxis } from "./FrequencyAxis";
import { AmplitudeAxis } from "./AmplitudeAxis";
import { MarkerOverlay } from "./MarkerOverlay";
import { SpectrumStatusBar } from "./SpectrumStatusBar";
import type { SpectrumFrame } from "../types";
import {
  FIXED_RENDER_PERIOD_MS,
  fixedRenderDecision,
} from "../rendering/renderSchedule";
import { spectrumBinFrequencyHz } from "../data/frequencyBins";
import {
  plotXToNormalizedFrequency,
  sharedHorizontalPlotRect,
  visibleFrequencyPlotRange,
  type FrequencyPlotRange,
} from "../rendering/plotGeometry";
import { IfOverflowWarning } from "./IfOverflowWarning";

const centerFrequencyRange=(centerHz:number,spanHz:number):FrequencyPlotRange=>({
  startHz:centerHz-spanHz/2,
  stopHz:centerHz+spanHz/2,
})

export function SpectrumPanel() {
  const glRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const latest = useRef<SpectrumFrame | null>(null);
  const overlayDirty = useRef(true);
  const initialDevice=useDeviceStore.getState()
  const frequencyRange=useRef(centerFrequencyRange(initialDevice.centerHz,initialDevice.spanHz));
  const drag = useRef<{ x: number; start: number; end: number } | null>(null);
  const cross = useRef<{ x: number; y: number } | null>(null);
  const [error, setError] = useState<string>();
  const center = useDeviceStore((s) => s.centerHz);
  const span = useDeviceStore((s) => s.spanHz);
  const referenceLevelDbm = useDeviceStore((s) => s.referenceDbm);
  useEffect(()=>{
    frequencyRange.current=centerFrequencyRange(center,span)
    overlayDirty.current=true
  },[center,span])
  useEffect(() => {
    useDisplayStore.getState().setSpectrumReferenceLevel(referenceLevelDbm);
  }, [referenceLevelDbm]);
  useEffect(() => {
    const canvas = glRef.current;
    const overlay = overlayRef.current;
    if (!canvas || !overlay) return;
    let renderer: SpectrumRenderer;
    latest.current = null;
    liveFrames.clear();
    useDisplayStore.getState().setMarker(null);
    try {
      renderer = new SpectrumRenderer(canvas);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Spectrum failed";
      const timer = window.setTimeout(() => setError(message), 0);
      return () => window.clearTimeout(timer);
    }
    let raf = 0;
    let dirty = true;
    let nextRenderDeadline = 0;
    let rendered = 0;
    let measuredAt = performance.now();
    let renderTimeMs = 0;
    let pendingFrames = 0;
    let pendingMerges = 0;
    const unsubscribe = liveFrames.subscribe((frame) => {
      latest.current = frame;
      frequencyRange.current={startHz:frame.startHz,stopHz:frame.stopHz}
      overlayDirty.current=true
      renderer.setFrame(
        frame.values,
        frame.intervalMaxValues??frame.values,
        frame.configurationGeneration,
      );
      dirty = true;
      pendingFrames++;
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
      const area = { ...horizontal, top: 7, bottom: h - 27 };
      const view = useDisplayStore.getState().viewport;
      const visible=visibleFrequencyPlotRange(frequencyRange.current,view)
      FrequencyAxis(ctx, area, visible.startHz, visible.stopHz);
      AmplitudeAxis(ctx, area, view.minDbm, view.maxDbm);
      MarkerOverlay(
        ctx,
        area,
        useDisplayStore.getState().marker,
        view.minDbm,
        view.maxDbm,
        visible.startHz,
        visible.stopHz,
      );
      if (cross.current) {
        ctx.strokeStyle = "rgba(115,215,239,.45)";
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(cross.current.x, area.top);
        ctx.lineTo(cross.current.x, area.bottom);
        ctx.moveTo(area.left, cross.current.y);
        ctx.lineTo(area.right, cross.current.y);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    };
    const animate = (now: number) => {
      const display = useDisplayStore.getState();
      const runtime = useRuntimeStore.getState();
      const hasFrame=latest.current!==null
      const decision =
        pendingFrames > 0
          ? { due: true, nextDeadline: now + FIXED_RENDER_PERIOD_MS }
          : hasFrame || dirty || overlayDirty.current
            ? fixedRenderDecision(now, nextRenderDeadline)
            : { due: false, nextDeadline: nextRenderDeadline };
      nextRenderDeadline = decision.nextDeadline;
      if (hasFrame && decision.due) {
        const renderStarted = performance.now();
        resizeCanvas(canvas);
        renderer.render(display.viewport, display.persistence);
        if (overlayDirty.current) {
          drawOverlay();
          overlayDirty.current = false;
        }
        renderTimeMs += performance.now() - renderStarted;
        pendingMerges += Math.max(0, pendingFrames - 1);
        pendingFrames = 0;
        dirty = false;
        rendered++;
      } else if (overlayDirty.current && decision.due) {
        drawOverlay();
        overlayDirty.current = false;
      }
      if (now - measuredAt >= 1000) {
        const elapsed = (now - measuredAt) / 1000;
        runtime.update({
          webglFps: Math.round(rendered / elapsed),
          spectrumRenderTimeMs: rendered ? renderTimeMs / rendered : 0,
          pendingSpectrumMerges: runtime.pendingSpectrumMerges + pendingMerges,
        });
        rendered = 0;
        renderTimeMs = 0;
        pendingMerges = 0;
        measuredAt = now;
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
      cancelAnimationFrame(raf);
      observer.disconnect();
      renderer.dispose();
    };
  }, []);
  const pointerPosition = (event: PointerEvent | WheelEvent) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
  };
  const placeMarker = (x: number, width: number) => {
    const frame = latest.current;
    if (!frame) return;
    const view = useDisplayStore.getState().viewport;
    const plotX = plotXToNormalizedFrequency(x,sharedHorizontalPlotRect(width));
    const normalized = view.start + plotX * (view.end - view.start);
    const bin = Math.round(normalized * (frame.values.length - 1));
    useDisplayStore
      .getState()
      .setMarker({
        bin,
        frequencyHz: spectrumBinFrequencyHz(frame, bin),
        amplitudeDbm: frame.values[bin],
      });
  };
  const onWheel = (event: WheelEvent) => {
    event.preventDefault();
    const p = pointerPosition(event);
    const view = useDisplayStore.getState().viewport;
    const cursor = plotXToNormalizedFrequency(p.x,sharedHorizontalPlotRect(p.width));
    const anchor = view.start + cursor * (view.end - view.start);
    const factor = event.deltaY > 0 ? 1.18 : 0.84;
    const width = Math.min(
      1,
      Math.max(0.015, (view.end - view.start) * factor),
    );
    const start = Math.max(0, Math.min(1 - width, anchor - cursor * width));
    useDisplayStore.getState().setViewport({ start, end: start + width });
  };
  const onPointerDown = (event: PointerEvent) => {
    const p = pointerPosition(event);
    drag.current = {
      x: p.x,
      start: useDisplayStore.getState().viewport.start,
      end: useDisplayStore.getState().viewport.end,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent) => {
    const p = pointerPosition(event);
    cross.current = { x: p.x, y: p.y };
    overlayDirty.current = true;
    if (!drag.current) return;
    const width = drag.current.end - drag.current.start;
    const delta = (-(p.x - drag.current.x) / sharedHorizontalPlotRect(p.width).width) * width;
    const start = Math.max(0, Math.min(1 - width, drag.current.start + delta));
    useDisplayStore.getState().setViewport({ start, end: start + width });
  };
  const onPointerUp = (event: PointerEvent) => {
    const p = pointerPosition(event);
    if (drag.current && Math.abs(p.x - drag.current.x) < 4)
      placeMarker(p.x, p.width);
    drag.current = null;
  };
  return (
    <section className="plot-panel spectrum-panel">
      <div
        className="plot-stage interactive"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          cross.current = null;
          overlayDirty.current = true;
        }}
        onDoubleClick={() => useDisplayStore.getState().resetViewport()}
      >
        <canvas ref={glRef} />
        <canvas className="overlay-canvas" ref={overlayRef} />
        <div className="spectrum-warning-overlay"><IfOverflowWarning /></div>
        {error && <div className="plot-error">{error}</div>}
      </div>
      <SpectrumStatusBar />
    </section>
  );
}
