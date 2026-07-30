import { create } from 'zustand'
import type { AnalyzerSourceType, ConnectionState, FrequencyScanStatus, Marker, ToolMode, Viewport } from './types'
import type { RfSwitchStatusApi } from './data/controlApi'
import { DEFAULT_SPECTRUM_DYNAMIC_RANGE_DB, spectrumRangeForReferenceLevel } from './rendering/amplitudeScale'

interface DeviceState {
  centerHz: number; stepHz: number; spanHz: number
  referenceDbm: number; attenuationDb: number; attenuationAutomatic:boolean; preamplifier: string; gainStrategy: string; amplitudeOffsetDb: number
  ifAgc: boolean; ifAgcTargetDbfs: number; ifAgcPeriodS: number; ifAgcGainDb: number|null
  rbwMode: string; rbwHz: number; vbwMode: string; vbwHz: number; window: string; detector: string
  resolutionTradeoffIndex:number;resolutionTradeoffState:'auto'|'matched'|'custom'|'pending'
  set: <K extends keyof Omit<DeviceState, 'set'>>(key: K, value: DeviceState[K]) => void
}

export const useDeviceStore = create<DeviceState>((set) => ({
  centerHz: 2.45e9, stepHz: 10e6, spanHz: 101.5625e6,
  referenceDbm: -10, attenuationDb: 0, attenuationAutomatic:false, preamplifier: 'auto', gainStrategy: 'low-noise', amplitudeOffsetDb: 0,
  ifAgc: true, ifAgcTargetDbfs: -9, ifAgcPeriodS: 0, ifAgcGainDb: null,
  rbwMode: 'auto', rbwHz: 60.306e3, resolutionTradeoffIndex:7,resolutionTradeoffState:'auto',vbwMode: 'ratio-0.1', vbwHz: 6.0306e3,
  window: 'blackman-nuttall', detector: 'positive-peak',
  set: (key, value) => set({ [key]: value } as Partial<DeviceState>),
}))

interface DisplayState {
  colormap: string; persistence: boolean; activeTool: ToolMode; viewport: Viewport; marker: Marker | null
  setTool: (tool: ToolMode) => void; setViewport: (viewport: Partial<Viewport>) => void; resetViewport: () => void
  setSpectrumReferenceLevel: (referenceLevelDbm: number) => void
  setMarker: (marker: Marker | null) => void; setPersistence: (enabled: boolean) => void
}
const defaultAmplitudeRange = spectrumRangeForReferenceLevel(-10, DEFAULT_SPECTRUM_DYNAMIC_RANGE_DB)
const defaultViewport: Viewport = { start: 0, end: 1, ...defaultAmplitudeRange }
export const useDisplayStore = create<DisplayState>((set) => ({
  colormap: 'turbo', persistence: true, activeTool: 'marker', viewport: defaultViewport, marker: null,
  setTool: (activeTool) => set({ activeTool }), setViewport: (v) => set((s) => ({ viewport: { ...s.viewport, ...v } })),
  resetViewport: () => set((s) => ({ viewport: { ...s.viewport, start: 0, end: 1 } })),
  setSpectrumReferenceLevel: (referenceLevelDbm) => set((s) => {
    const dynamicRangeDb = s.viewport.maxDbm - s.viewport.minDbm
    return { viewport: { ...s.viewport, ...spectrumRangeForReferenceLevel(referenceLevelDbm, dynamicRangeDb) } }
  }),
  setMarker: (marker) => set({ marker }),
  setPersistence: (persistence) => set({ persistence }),
}))

interface RuntimeState {
  source: AnalyzerSourceType; connection: ConnectionState; fps: number; spectrumFps: number; waterfallFps: number; sdkFps: number
  waterfallBatchFps:number; waterfallRowsUploadedFps:number; waterfallRowsPerSecond:number; waterfallRowsPerBatch:number
  waterfallTextureRows:number; waterfallHistorySeconds:number; staleBatchesRejected:number; malformedBatchesRejected:number; textureWrapCount:number
  validWaterfallRows:number
  waterfallWriteRow:number;waterfallVisibleStartRow:number;waterfallOutOfOrderBatches:number;waterfallOutOfOrderRows:number;waterfallSequenceGaps:number;waterfallReceiveOutOfOrder:number
  visibleTimeSpanSeconds:number;visibleWaterfallRows:number;webglTargetFps:number;webglFps:number
  spectrogramFps:number;spectrumRenderTimeMs:number;spectrogramUploadTimeMs:number;spectrogramRenderTimeMs:number;pendingSpectrumMerges:number
  waterfallPendingBatchesReplaced:number
  waterfallPendingRowsReplaced:number
  pointCount: number; droppedFrames: number; replacedSnapshots: number; actualRbwHz: number; actualSpanHz: number
  fftSize:number|null;frequencyBinSpacingHz:number|null;tracesPerSpectrumFrame:number|null;tracesPerWaterfallRow:number|null
  waterfallFloorDbm: number; waterfallCeilingDbm: number
  configurationGeneration:number; reconfiguring:boolean; frequencyScan:FrequencyScanStatus
  playbackActive:boolean; playbackState:string
  ifOverflow:boolean
  sweepTimeMs: number; websocketBytes: number; acquisitionErrors: number; lastError?: string
  update: (values: Partial<Omit<RuntimeState, 'update'>>) => void
}
export const useRuntimeStore = create<RuntimeState>((set) => ({
  source: 'simulator', connection: 'mock', fps: 0, spectrumFps: 0, waterfallFps: 0, sdkFps: 0,
  waterfallBatchFps:0,waterfallRowsUploadedFps:0,waterfallRowsPerSecond:60,waterfallRowsPerBatch:1,
  waterfallTextureRows:4096,waterfallHistorySeconds:4096/60,validWaterfallRows:0,waterfallWriteRow:0,waterfallVisibleStartRow:0,waterfallOutOfOrderBatches:0,waterfallOutOfOrderRows:0,waterfallSequenceGaps:0,waterfallReceiveOutOfOrder:0,visibleTimeSpanSeconds:5,visibleWaterfallRows:300,webglTargetFps:60,webglFps:0,spectrogramFps:0,spectrumRenderTimeMs:0,spectrogramUploadTimeMs:0,spectrogramRenderTimeMs:0,pendingSpectrumMerges:0,staleBatchesRejected:0,malformedBatchesRejected:0,textureWrapCount:0,
  waterfallPendingBatchesReplaced:0,waterfallPendingRowsReplaced:0,
  pointCount: 1024, droppedFrames: 0, replacedSnapshots: 0, actualRbwHz: 60.306e3, actualSpanHz: 101.5625e6,
  fftSize:null,frequencyBinSpacingHz:null,tracesPerSpectrumFrame:null,tracesPerWaterfallRow:null,
  waterfallFloorDbm:-112, waterfallCeilingDbm:-10,
  configurationGeneration:0, reconfiguring:false,
  playbackActive:false, playbackState:'idle',
  frequencyScan:{running:false,state:'idle',active_entry_id:null,active_index:null,active_count:0,verified_center_frequency_hz:null,dwell_duration_seconds:null,remaining_dwell_seconds:null,last_error:null},
  ifOverflow:false,
  sweepTimeMs: 40, websocketBytes: 0, acquisitionErrors: 0,
  update: (values) => set(values),
}))

interface RfSwitchState extends RfSwitchStatusApi {
  loading:boolean
  applying:boolean
  update:(values:Partial<Omit<RfSwitchState,'update'>>) => void
}

export const useRfSwitchStore=create<RfSwitchState>((set)=>({
  connection_state:'disabled',hardware_present:false,available:false,connected:false,backend:'disabled',simulated:false,
  requested_path:null,requested_port:null,reported_path:null,reported_port:null,expected_fail_safe_path:null,
  raw_address:null,raw_gpio_value:null,gpio_value:null,readback_matches_request:false,verification:'unavailable',
  last_error:null,reconnect_attempts:0,last_connected_at:null,last_disconnected_at:null,updated_at_monotonic:0,loading:true,applying:false,
  update:(values)=>set(values),
}))
