import { liveFrames } from "./liveFrames";
import { useDeviceStore, useRuntimeStore } from "../stores";
import type { ParsedAnalyzerMessage } from "./binaryProtocol";
import { acceptsConfigurationGeneration } from "./binaryProtocol";

type WorkerResult =
  | ParsedAnalyzerMessage
  | { error: string; kind?: "waterfall" | "other" }
  | { rejected: "stale"; kind: "spectrum" | "waterfall" };
export class WebSocketSpectrumSource {
  private socket: WebSocket | null = null;
  private worker: Worker | null = null;
  private spectrumTimes: number[] = [];
  private waterfallTimes: number[] = [];
  private waterfallBatchTimes: number[] = [];
  private lastSpectrumMetrics = 0;
  private lastWaterfallMetrics = 0;
  private waterfallGeneration: number | null = null;
  private lastWaterfallBatchSequence: number | null = null;
  private lastWaterfallRowSequence: number | null = null;
  private waterfallSequenceGaps = 0;
  private waterfallReceiveOutOfOrder = 0;
  private bytes = 0;
  constructor(private readonly url: string) {}
  start() {
    if (this.socket) return;
    useRuntimeStore
      .getState()
      .update({
        source: "san90",
        connection: "connecting",
        lastError: undefined,
        ifOverflow: false,
      });
    this.worker = new Worker(
      new URL("../workers/frameParser.worker.ts", import.meta.url),
      { type: "module" },
    );
    this.worker.onmessage = ({ data }: MessageEvent<WorkerResult>) => {
      if ("error" in data) {
        const runtime = useRuntimeStore.getState();
        runtime.update({
          droppedFrames: runtime.droppedFrames + 1,
          malformedBatchesRejected:
            runtime.malformedBatchesRejected +
            (data.kind === "waterfall" ? 1 : 0),
          lastError: data.error,
        });
        return;
      }
      if ("rejected" in data) {
        const runtime = useRuntimeStore.getState();
        runtime.update({
          staleBatchesRejected:
            runtime.staleBatchesRejected + (data.kind === "waterfall" ? 1 : 0),
        });
        return;
      }
      const now = performance.now();
      if (data.kind === "spectrum") {
        if (
          !acceptsConfigurationGeneration(
            data.frame.configurationGeneration,
            useRuntimeStore.getState().configurationGeneration,
          )
        )
          return;
        const runtime = useRuntimeStore.getState();
        if (
          data.frame.configurationGeneration !== runtime.configurationGeneration
        )
          runtime.update({
            configurationGeneration: data.frame.configurationGeneration,
          });
        this.record(this.spectrumTimes, now);
        liveFrames.publish(data.frame);
        const device = useDeviceStore.getState(),
          center =
            data.frame.centerHz ?? (data.frame.startHz + data.frame.stopHz) / 2,
          span = data.frame.spanHz ?? data.frame.stopHz - data.frame.startHz;
        if (device.centerHz !== center) device.set("centerHz", center);
        if (device.spanHz !== span) device.set("spanHz", span);
        if (
          data.frame.referenceLevelDbm !== undefined &&
          device.referenceDbm !== data.frame.referenceLevelDbm
        )
          device.set("referenceDbm", data.frame.referenceLevelDbm);
        if (data.frame.rbwHz !== undefined && device.rbwHz !== data.frame.rbwHz)
          device.set("rbwHz", data.frame.rbwHz);
        const actualRbwHz = data.frame.rbwHz ?? 0,
          actualSpanHz =
            data.frame.spanHz ?? data.frame.stopHz - data.frame.startHz;
        if (
          runtime.source !== (data.frame.source ?? "san90") ||
          runtime.pointCount !== data.frame.values.length ||
          runtime.actualRbwHz !== actualRbwHz ||
          runtime.actualSpanHz !== actualSpanHz
        )
          runtime.update({
            source: data.frame.source ?? "san90",
            pointCount: data.frame.values.length,
            actualRbwHz,
            actualSpanHz,
          });
        if (now - this.lastSpectrumMetrics >= 1000) {
          runtime.update({
            spectrumFps: this.spectrumTimes.length,
            fps: this.spectrumTimes.length,
            websocketBytes: this.bytes,
          });
          this.lastSpectrumMetrics = now;
        }
      } else if (data.kind === "waterfall") {
        if (
          !acceptsConfigurationGeneration(
            data.frame.configurationGeneration,
            useRuntimeStore.getState().configurationGeneration,
          )
        )
          return;
        const runtime = useRuntimeStore.getState();
        if(this.waterfallGeneration!==data.frame.configurationGeneration){this.waterfallGeneration=data.frame.configurationGeneration;this.lastWaterfallBatchSequence=null;this.lastWaterfallRowSequence=null}
        if(this.lastWaterfallBatchSequence!==null){
          if(data.frame.batchSequence<=this.lastWaterfallBatchSequence)this.waterfallReceiveOutOfOrder++
          else if(data.frame.batchSequence>this.lastWaterfallBatchSequence+1)this.waterfallSequenceGaps+=data.frame.batchSequence-this.lastWaterfallBatchSequence-1
        }
        if(this.lastWaterfallRowSequence!==null&&data.frame.firstRowSequence>this.lastWaterfallRowSequence+1)this.waterfallSequenceGaps+=data.frame.firstRowSequence-this.lastWaterfallRowSequence-1
        this.lastWaterfallBatchSequence=data.frame.batchSequence
        this.lastWaterfallRowSequence=data.frame.firstRowSequence+data.frame.rowCount-1
        if (
          data.frame.configurationGeneration !== runtime.configurationGeneration
        )
          runtime.update({
            configurationGeneration: data.frame.configurationGeneration,
          });
        this.record(this.waterfallBatchTimes, now);
        for (let row = 0; row < data.frame.rowCount; row++)
          this.record(this.waterfallTimes, now);
        liveFrames.publishWaterfall(data.frame);
        if (now - this.lastWaterfallMetrics >= 1000) {
          useRuntimeStore
            .getState()
            .update({
              waterfallFps: this.waterfallTimes.length,
              waterfallBatchFps: this.waterfallBatchTimes.length,
              waterfallRowsPerBatch: data.frame.rowCount,
              waterfallSequenceGaps:this.waterfallSequenceGaps,
              waterfallReceiveOutOfOrder:this.waterfallReceiveOutOfOrder,
              ...(data.frame.nominalRowPeriodNs > 0n
                ? {
                    waterfallRowsPerSecond:
                      1e9 / Number(data.frame.nominalRowPeriodNs),
                  }
                : {}),
            });
          this.lastWaterfallMetrics = now;
        }
      } else {
        const status = data.status;
        if (status.amplitude_offset_db !== undefined)
          useDeviceStore.getState().set("amplitudeOffsetDb", status.amplitude_offset_db);
        const scale = status.waterfall_raw_scale_db;
        const offset = status.waterfall_raw_offset_dbm;
        const rowsPerSecond =
          status.waterfall_rows_per_second ?? status.waterfall_publish_fps;
        useRuntimeStore
          .getState()
          .update({
            source: status.source,
            connection: status.acquisition_running ? "connected" : "stopped",
            sdkFps: status.sdk_frames_per_second,
            pointCount:
              status.point_count ?? useRuntimeStore.getState().pointCount,
            replacedSnapshots: status.replaced_display_snapshots,
            droppedFrames: status.invalid_frames,
            acquisitionErrors: status.acquisition_errors,
            ifOverflow: status.if_overflow,
            lastError: status.last_error ?? undefined,
            reconfiguring: status.reconfiguring,
            configurationGeneration: Math.max(
              status.configuration_generation,
              useRuntimeStore.getState().configurationGeneration,
            ),
            waterfallRowsPerSecond: rowsPerSecond,
            waterfallRowsPerBatch:
              status.waterfall_rows_per_batch ??
              useRuntimeStore.getState().waterfallRowsPerBatch,
            waterfallHistorySeconds:
              useRuntimeStore.getState().waterfallTextureRows / rowsPerSecond,
            visibleTimeSpanSeconds: status.visible_time_span_seconds ?? 5,
            visibleWaterfallRows:
              status.visible_rows ?? Math.round(rowsPerSecond * 5),
            webglTargetFps: status.webgl_target_fps ?? 60,
            actualRbwHz:
              status.actual_rbw_hz ?? useRuntimeStore.getState().actualRbwHz,
            fftSize: status.fft_size ?? null,
            frequencyBinSpacingHz: status.frequency_bin_spacing_hz ?? null,
            tracesPerSpectrumFrame: status.traces_per_spectrum_frame ?? null,
            tracesPerWaterfallRow: status.traces_per_waterfall_row ?? null,
            ...(scale != null && offset != null
              ? {
                  waterfallFloorDbm: offset,
                  waterfallCeilingDbm: offset + 255 * scale,
                }
              : {}),
          });
      }
    };
    this.worker.onerror = () =>
      useRuntimeStore
        .getState()
        .update({
          connection: "error",
          lastError: "Binary frame worker failed",
        });
    const socket = new WebSocket(this.url);
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    socket.onopen = () =>
      useRuntimeStore
        .getState()
        .update({ connection: "connected", source: "san90" });
    socket.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (event.data instanceof ArrayBuffer) {
        this.bytes += event.data.byteLength;
        this.worker?.postMessage(event.data, [event.data]);
      }
    };
    socket.onerror = () =>
      useRuntimeStore
        .getState()
        .update({
          connection: "error",
          lastError: "Analyzer connection failed",
        });
    socket.onclose = () => {
      if (this.socket)
        useRuntimeStore
          .getState()
          .update({
            connection: "error",
            lastError: "Analyzer connection closed",
            ifOverflow: false,
          });
      this.socket = null;
    };
  }
  private record(samples: number[], now: number) {
    samples.push(now);
    while (samples.length && samples[0] < now - 1000) samples.shift();
  }
  stop() {
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
    this.worker?.terminate();
    this.worker = null;
    useRuntimeStore.getState().update({ connection: "stopped", ifOverflow: false });
  }
}
