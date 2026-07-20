import type { SpectrumFrame, WaterfallBatch } from '../types'

export type FrameListener = (frame: SpectrumFrame) => void
class LiveFrameBus {
  private listeners = new Set<FrameListener>()
  private waterfallListeners = new Set<(frame: WaterfallBatch) => void>()
  private latest: SpectrumFrame | null = null
  publish(frame: SpectrumFrame) {
    this.latest = frame; this.listeners.forEach((listener) => listener(frame))
    if (frame.waterfall.length) this.publishWaterfall({
      sequence: frame.sequence, batchSequence:frame.sequence, firstRowSequence:frame.sequence, rowCount:1,
      pointCount:frame.waterfall.length, nominalRowPeriodNs:0n, source: frame.source ?? 'simulator', deviceTimestampNs: frame.deviceTimestampNs ?? 0n,
      hostTimestampNs: frame.hostTimestampNs ?? BigInt(Math.round(frame.timestamp * 1e6)), startHz: frame.startHz,
      centerHz: frame.centerHz ?? (frame.startHz + frame.stopHz) / 2, stopHz: frame.stopHz,
      spanHz: frame.spanHz ?? frame.stopHz - frame.startHz, rbwHz: frame.rbwHz ?? 0,
      referenceLevelDbm: frame.referenceLevelDbm ?? 0, values: frame.waterfall,
      configurationGeneration: frame.configurationGeneration,
    })
  }
  publishWaterfall(frame: WaterfallBatch) { this.waterfallListeners.forEach((listener) => listener(frame)) }
  subscribe(listener: FrameListener) { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  subscribeWaterfall(listener: (frame: WaterfallBatch) => void) { this.waterfallListeners.add(listener); return () => this.waterfallListeners.delete(listener) }
  getLatest() { return this.latest }
  clear() { this.latest=null }
}
export const liveFrames = new LiveFrameBus()
