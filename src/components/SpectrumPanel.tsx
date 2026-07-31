import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type WheelEvent,
} from "react";
import { liveFrames } from "../data/liveFrames";
import { aiDetections } from "../data/aiDetections";
import {
  analyzerApi,
  type AnalyzerCapabilitiesApi,
} from "../data/controlApi";
import {
  commitCenterFrequencyHz,
  DEFAULT_CENTER_FREQUENCY_LIMITS,
  type CenterFrequencyLimits,
} from "../data/centerFrequencyControl";
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
import {
  calculateSpectrumPan,
  formatPanDelta,
  formatPanFrequency,
  PAN_TUNE_TIMEOUT_MS,
  shouldCommitSpectrumPan,
  type SpectrumPanCalculation,
} from "./spectrumPan";

const centerFrequencyRange = (
  centerHz: number,
  spanHz: number,
): FrequencyPlotRange => ({
  startHz: centerHz - spanHz / 2,
  stopHz: centerHz + spanHz / 2,
});

interface ViewportDrag {
  x: number;
  start: number;
  end: number;
}

interface PanDrag {
  pointerId: number;
  startClientX: number;
  latestClientX: number;
  startCenterHz: number;
  actualSpanHz: number;
  plotWidthPx: number;
  stageWidthPx: number;
  configurationGeneration: number;
  calculation: SpectrumPanCalculation;
  commitStarted: boolean;
}

interface PendingTune {
  actualCenterHz: number;
  configurationGeneration: number;
}

function panUnavailableReason() {
  const runtime = useRuntimeStore.getState();
  if (runtime.playbackActive || runtime.source === "playback")
    return "Pan tuning is unavailable during playback.";
  if (
    runtime.frequencyScan.running
    || ["tuning", "dwelling", "stopping"].includes(runtime.frequencyScan.state)
  )
    return "Pan tuning is unavailable during Frequency Scan.";
  if (!["connected", "mock"].includes(runtime.connection))
    return "Pan tuning requires a connected analyzer.";
  if (runtime.reconfiguring)
    return "Pan tuning is unavailable while the analyzer is reconfiguring.";
  return null;
}

export function SpectrumPanel() {
  const glRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const panOverlayRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<SpectrumRenderer | null>(null);
  const latest = useRef<SpectrumFrame | null>(null);
  const overlayDirty = useRef(true);
  const renderDirty = useRef(true);
  const initialDevice = useDeviceStore.getState();
  const frequencyRange = useRef(
    centerFrequencyRange(initialDevice.centerHz, initialDevice.spanHz),
  );
  const previewFrequencyRange = useRef<FrequencyPlotRange | null>(null);
  const viewportDrag = useRef<ViewportDrag | null>(null);
  const panDrag = useRef<PanDrag | null>(null);
  const panUpdateRaf = useRef(0);
  const panTuneTimer = useRef(0);
  const pendingTune = useRef<PendingTune | null>(null);
  const cross = useRef<{ x: number; y: number } | null>(null);
  const limits = useRef<CenterFrequencyLimits>(
    DEFAULT_CENTER_FREQUENCY_LIMITS,
  );
  const cancelPanRef = useRef<(showError?: string) => void>(() => undefined);
  const [error, setError] = useState<string>();
  const center = useDeviceStore((s) => s.centerHz);
  const span = useDeviceStore((s) => s.spanHz);
  const referenceLevelDbm = useDeviceStore((s) => s.referenceDbm);
  const activeTool = useDisplayStore((s) => s.activeTool);
  const panPhase = useDisplayStore((s) => s.panPhase);
  const runtimeSource = useRuntimeStore((s) => s.source);
  const runtimeConnection = useRuntimeStore((s) => s.connection);
  const runtimeReconfiguring = useRuntimeStore((s) => s.reconfiguring);
  const playbackActive = useRuntimeStore((s) => s.playbackActive);
  const scanRunning = useRuntimeStore((s) => s.frequencyScan.running);
  const scanState = useRuntimeStore((s) => s.frequencyScan.state);

  useEffect(() => {
    frequencyRange.current = centerFrequencyRange(center, span);
    overlayDirty.current = true;
  }, [center, span]);

  useEffect(() => {
    useDisplayStore.getState().setSpectrumReferenceLevel(referenceLevelDbm);
  }, [referenceLevelDbm]);

  useEffect(() => {
    let active = true;
    if (runtimeSource !== "san90") {
      limits.current = DEFAULT_CENTER_FREQUENCY_LIMITS;
      return;
    }
    void analyzerApi.capabilities()
      .then((capabilities: AnalyzerCapabilitiesApi) => {
        if (!active) return;
        limits.current = {
          minimumHz:
            capabilities.center_frequency_min_hz
            ?? DEFAULT_CENTER_FREQUENCY_LIMITS.minimumHz,
          maximumHz:
            capabilities.center_frequency_max_hz
            ?? DEFAULT_CENTER_FREQUENCY_LIMITS.maximumHz,
        };
      })
      .catch(() => {
        // The normal status/control path reports connectivity failures.
      });
    return () => {
      active = false;
    };
  }, [runtimeSource]);

  const setPanOverlay = (
    mode: "hidden" | "dragging" | "tuning",
    startCenterHz?: number,
    calculation?: SpectrumPanCalculation,
  ) => {
    const element = panOverlayRef.current;
    if (!element) return;
    element.hidden = mode === "hidden";
    element.dataset.mode = mode;
    if (mode === "hidden") {
      element.replaceChildren();
      return;
    }
    if (mode === "tuning") {
      element.textContent = "PAN · TUNING…";
      return;
    }
    if (startCenterHz == null || calculation == null) return;
    element.textContent = [
      "PAN",
      `Center: ${formatPanFrequency(startCenterHz)} → ${formatPanFrequency(calculation.targetCenterHz)}`,
      `Δf: ${formatPanDelta(calculation.frequencyDeltaHz)}`,
      calculation.clamped ? "LIMIT" : "",
    ].filter(Boolean).join(" · ");
  };

  const clearPanVisual = () => {
    if (panUpdateRaf.current) {
      cancelAnimationFrame(panUpdateRaf.current);
      panUpdateRaf.current = 0;
    }
    previewFrequencyRange.current = null;
    rendererRef.current?.setPanOffsetPixels(0, 1);
    rendererRef.current?.setPanDimmed(false);
    setPanOverlay("hidden");
    overlayDirty.current = true;
    renderDirty.current = true;
  };

  const releasePanPointer = () => {
    const drag = panDrag.current;
    const stage = overlayRef.current?.parentElement;
    if (
      drag
      && stage
      && stage.hasPointerCapture?.(drag.pointerId)
    ) {
      stage.releasePointerCapture(drag.pointerId);
    }
  };

  const cancelPan = (showError?: string) => {
    if (useDisplayStore.getState().panPhase === "tuning") return;
    releasePanPointer();
    panDrag.current = null;
    pendingTune.current = null;
    clearPanVisual();
    const available = panUnavailableReason() == null;
    useDisplayStore.getState().setPanPhase(
      useDisplayStore.getState().activeTool === "pan" && available
        ? "armed"
        : "off",
    );
    if (showError) useRuntimeStore.getState().update({ lastError: showError });
  };
  useEffect(() => {
    cancelPanRef.current = cancelPan;
  });

  const confirmTuneFromFrame = (frame: SpectrumFrame) => {
    const expected = pendingTune.current;
    if (!expected) return;
    const frameCenter = frame.centerHz ?? (frame.startHz + frame.stopHz) / 2;
    if (
      frame.configurationGeneration !== expected.configurationGeneration
      || Math.abs(frameCenter - expected.actualCenterHz) > 1
    ) return;
    pendingTune.current = null;
    panDrag.current = null;
    if (panTuneTimer.current) {
      window.clearTimeout(panTuneTimer.current);
      panTuneTimer.current = 0;
    }
    clearPanVisual();
    useDisplayStore.getState().setPanPhase(
      useDisplayStore.getState().activeTool === "pan" ? "armed" : "off",
    );
  };

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
      rendererRef.current = renderer;
    } catch (e) {
      const message = e instanceof Error ? e.message : "Spectrum failed";
      const timer = window.setTimeout(() => setError(message), 0);
      return () => window.clearTimeout(timer);
    }
    let raf = 0;
    let nextRenderDeadline = 0;
    let rendered = 0;
    let measuredAt = performance.now();
    let renderTimeMs = 0;
    let pendingFrames = 0;
    let pendingMerges = 0;
    const unsubscribe = liveFrames.subscribe((frame) => {
      latest.current = frame;
      frequencyRange.current = { startHz: frame.startHz, stopHz: frame.stopHz };
      confirmTuneFromFrame(frame);
      overlayDirty.current = true;
      renderer.setFrame(
        frame.values,
        frame.intervalMaxValues ?? frame.values,
        frame.configurationGeneration,
      );
      renderDirty.current = true;
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
      const horizontal = sharedHorizontalPlotRect(w);
      const area = { ...horizontal, top: 7, bottom: h - 27 };
      const display = useDisplayStore.getState();
      const range = previewFrequencyRange.current ?? frequencyRange.current;
      const visible = visibleFrequencyPlotRange(range, display.viewport);
      FrequencyAxis(ctx, area, visible.startHz, visible.stopHz);
      AmplitudeAxis(
        ctx,
        area,
        display.viewport.minDbm,
        display.viewport.maxDbm,
      );
      if (!["dragging", "tuning"].includes(display.panPhase)) {
        MarkerOverlay(
          ctx,
          area,
          display.marker,
          display.viewport.minDbm,
          display.viewport.maxDbm,
          visible.startHz,
          visible.stopHz,
        );
      }
      if (cross.current && display.panPhase !== "tuning") {
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
      const hasFrame = latest.current !== null;
      const decision =
        pendingFrames > 0
          ? { due: true, nextDeadline: now + FIXED_RENDER_PERIOD_MS }
          : hasFrame || renderDirty.current || overlayDirty.current
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
        renderDirty.current = false;
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
          pendingSpectrumMerges:
            runtime.pendingSpectrumMerges + pendingMerges,
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
      const nextWidth = canvas.clientWidth;
      if (
        panDrag.current
        && Math.abs(nextWidth - panDrag.current.stageWidthPx) > 1
      ) cancelPanRef.current();
      renderDirty.current = true;
      overlayDirty.current = true;
    });
    observer.observe(canvas);
    const unsubStore = useDisplayStore.subscribe(() => {
      renderDirty.current = true;
      overlayDirty.current = true;
    });
    return () => {
      unsubscribe();
      unsubStore();
      cancelAnimationFrame(raf);
      if (panUpdateRaf.current) cancelAnimationFrame(panUpdateRaf.current);
      if (panTuneTimer.current) window.clearTimeout(panTuneTimer.current);
      observer.disconnect();
      renderer.dispose();
      rendererRef.current = null;
    };
    // Renderer/subscription ownership is intentionally mount-scoped.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const unavailable = panUnavailableReason();
    if (activeTool !== "pan") {
      if (panPhase !== "tuning") cancelPan();
      useDisplayStore.getState().setPanPhase("off");
      return;
    }
    if (unavailable && panPhase !== "tuning") {
      cancelPan();
      useDisplayStore.getState().setPanPhase("off");
      return;
    }
    if (panPhase === "off")
      useDisplayStore.getState().setPanPhase("armed");
  // Pan availability is synchronized from the narrow runtime fields below.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeTool,
    playbackActive,
    runtimeConnection,
    runtimeReconfiguring,
    runtimeSource,
    scanRunning,
    scanState,
  ]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && panDrag.current) {
        event.preventDefault();
        cancelPan();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // The handler reads the current drag/store state through stable refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const plotX = plotXToNormalizedFrequency(
      x,
      sharedHorizontalPlotRect(width),
    );
    const normalized = view.start + plotX * (view.end - view.start);
    const bin = Math.round(normalized * (frame.values.length - 1));
    useDisplayStore.getState().setMarker({
      bin,
      frequencyHz: spectrumBinFrequencyHz(frame, bin),
      amplitudeDbm: frame.values[bin],
    });
  };

  const onWheel = (event: WheelEvent) => {
    if (useDisplayStore.getState().activeTool === "pan") return;
    event.preventDefault();
    const p = pointerPosition(event);
    const view = useDisplayStore.getState().viewport;
    const cursor = plotXToNormalizedFrequency(
      p.x,
      sharedHorizontalPlotRect(p.width),
    );
    const anchor = view.start + cursor * (view.end - view.start);
    const factor = event.deltaY > 0 ? 1.18 : 0.84;
    const width = Math.min(
      1,
      Math.max(0.015, (view.end - view.start) * factor),
    );
    const start = Math.max(
      0,
      Math.min(1 - width, anchor - cursor * width),
    );
    useDisplayStore.getState().setViewport({ start, end: start + width });
  };

  const updatePanVisual = () => {
    panUpdateRaf.current = 0;
    const drag = panDrag.current;
    if (!drag || drag.commitStarted) return;
    const deltaX = drag.latestClientX - drag.startClientX;
    drag.calculation = calculateSpectrumPan(
      drag.startCenterHz,
      deltaX,
      drag.plotWidthPx,
      drag.actualSpanHz,
      limits.current,
    );
    rendererRef.current?.setPanOffsetPixels(
      drag.calculation.effectiveDeltaX,
      drag.plotWidthPx,
    );
    previewFrequencyRange.current = centerFrequencyRange(
      drag.calculation.targetCenterHz,
      drag.actualSpanHz,
    );
    setPanOverlay("dragging", drag.startCenterHz, drag.calculation);
    renderDirty.current = true;
    overlayDirty.current = true;
  };

  const schedulePanVisual = () => {
    if (!panUpdateRaf.current)
      panUpdateRaf.current = requestAnimationFrame(updatePanVisual);
  };

  const onPointerDown = (event: PointerEvent) => {
    const p = pointerPosition(event);
    const display = useDisplayStore.getState();
    if (display.activeTool === "pan") {
      if (display.panPhase !== "armed" || panUnavailableReason()) return;
      const frame = latest.current;
      if (!frame) return;
      const plot = sharedHorizontalPlotRect(p.width);
      const plotBottom = p.height - 27;
      if (
        p.x < plot.left
        || p.x > plot.right
        || p.y < 7
        || p.y > plotBottom
      ) return;
      const startCenterHz =
        frame.centerHz ?? (frame.startHz + frame.stopHz) / 2;
      const actualSpanHz = frame.stopHz - frame.startHz;
      const calculation = calculateSpectrumPan(
        startCenterHz,
        0,
        plot.width,
        actualSpanHz,
        limits.current,
      );
      panDrag.current = {
        pointerId: event.pointerId,
        startClientX: event.clientX,
        latestClientX: event.clientX,
        startCenterHz,
        actualSpanHz,
        plotWidthPx: plot.width,
        stageWidthPx: p.width,
        configurationGeneration: frame.configurationGeneration,
        calculation,
        commitStarted: false,
      };
      cross.current = null;
      useDisplayStore.getState().setPanPhase("dragging");
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
      return;
    }
    viewportDrag.current = {
      x: p.x,
      start: display.viewport.start,
      end: display.viewport.end,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent) => {
    const p = pointerPosition(event);
    const drag = panDrag.current;
    if (drag && event.pointerId === drag.pointerId) {
      if (Math.abs(p.width - drag.stageWidthPx) > 1) {
        cancelPan();
        return;
      }
      drag.latestClientX = event.clientX;
      schedulePanVisual();
      return;
    }
    cross.current = { x: p.x, y: p.y };
    overlayDirty.current = true;
    if (!viewportDrag.current) return;
    const width = viewportDrag.current.end - viewportDrag.current.start;
    const delta =
      (-(p.x - viewportDrag.current.x)
        / sharedHorizontalPlotRect(p.width).width)
      * width;
    const start = Math.max(
      0,
      Math.min(1 - width, viewportDrag.current.start + delta),
    );
    useDisplayStore.getState().setViewport({ start, end: start + width });
  };

  const beginTune = async (drag: PanDrag) => {
    drag.commitStarted = true;
    rendererRef.current?.setPanDimmed(true);
    setPanOverlay("tuning");
    aiDetections.clear();
    useDisplayStore.getState().setPanPhase("tuning");
    renderDirty.current = true;
    const result = await commitCenterFrequencyHz(
      drag.calculation.targetCenterHz,
      limits.current,
    );
    if (!result) {
      panDrag.current = null;
      pendingTune.current = null;
      clearPanVisual();
      useDisplayStore.getState().setPanPhase(
        useDisplayStore.getState().activeTool === "pan" ? "armed" : "off",
      );
      return;
    }
    pendingTune.current = {
      actualCenterHz: result.actualCenterHz,
      configurationGeneration: result.configurationGeneration,
    };
    const currentFrame = latest.current;
    if (
      currentFrame
      && currentFrame.configurationGeneration
        !== drag.configurationGeneration
    ) confirmTuneFromFrame(currentFrame);
    if (!pendingTune.current) return;
    panTuneTimer.current = window.setTimeout(() => {
      pendingTune.current = null;
      panDrag.current = null;
      clearPanVisual();
      useDisplayStore.getState().setPanPhase(
        useDisplayStore.getState().activeTool === "pan" ? "armed" : "off",
      );
      useRuntimeStore.getState().update({
        lastError:
          "Pan tune timed out waiting for the verified analyzer data packet",
      });
    }, PAN_TUNE_TIMEOUT_MS);
  };

  const onPointerUp = (event: PointerEvent) => {
    const p = pointerPosition(event);
    const drag = panDrag.current;
    if (drag && event.pointerId === drag.pointerId) {
      drag.latestClientX = event.clientX;
      updatePanVisual();
      releasePanPointer();
      const deltaX = drag.latestClientX - drag.startClientX;
      if (
        !shouldCommitSpectrumPan(
          deltaX,
          drag.calculation,
          drag.plotWidthPx,
          drag.actualSpanHz,
        )
      ) {
        panDrag.current = null;
        clearPanVisual();
        useDisplayStore.getState().setPanPhase("armed");
        return;
      }
      void beginTune(drag);
      return;
    }
    if (
      viewportDrag.current
      && Math.abs(p.x - viewportDrag.current.x) < 4
    ) placeMarker(p.x, p.width);
    viewportDrag.current = null;
  };

  const unavailable = panUnavailableReason();
  return (
    <section className="plot-panel spectrum-panel">
      <div
        className={[
          "plot-stage",
          "interactive",
          activeTool === "pan" ? "pan-tool" : "",
          panPhase === "dragging" ? "is-pan-dragging" : "",
          panPhase === "tuning" ? "is-pan-tuning" : "",
        ].filter(Boolean).join(" ")}
        data-pan-phase={panPhase}
        aria-disabled={activeTool === "pan" && unavailable ? "true" : undefined}
        title={activeTool === "pan" && unavailable ? unavailable : undefined}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => cancelPan()}
        onPointerLeave={() => {
          if (!panDrag.current) {
            cross.current = null;
            overlayDirty.current = true;
          }
        }}
        onDoubleClick={() => {
          if (activeTool !== "pan")
            useDisplayStore.getState().resetViewport();
        }}
      >
        <canvas ref={glRef} />
        <canvas className="overlay-canvas" ref={overlayRef} />
        <div
          ref={panOverlayRef}
          className="spectrum-pan-overlay"
          role="status"
          aria-live="polite"
          hidden
        />
        <div className="spectrum-warning-overlay">
          <IfOverflowWarning />
        </div>
        {error && <div className="plot-error">{error}</div>}
      </div>
      <SpectrumStatusBar />
    </section>
  );
}
