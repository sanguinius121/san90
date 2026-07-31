export type ConnectionState = 'mock' | 'connecting' | 'connected' | 'stopped' | 'error'
import type { PlaybackStatus } from './types/playback'

export type AnalyzerSourceType = 'simulator' | 'san90' | 'playback'
export type ToolMode = 'peak' | 'marker' | 'pan'
export type PanPhase = 'off' | 'armed' | 'dragging' | 'tuning'
export type SelectOption = { label: string; value: string }
export type Marker = { bin: number; frequencyHz: number; amplitudeDbm: number }

export interface AiFrequencyDetection {
  label: string
  confidence: number
  frequencyStartHz: number
  frequencyStopHz: number
  classId?: number
}

export interface AiDetectionResult {
  source?: AnalyzerSourceType
  sequence: number | null
  timestampNs: number | null
  generatedAt: number | null
  receivedAtNs: number | null
  detections: AiFrequencyDetection[]
}

export type FrequencyScanControllerState = 'idle' | 'tuning' | 'dwelling' | 'stopping' | 'error'

export interface FrequencyScanStatus {
  running: boolean
  state: FrequencyScanControllerState
  active_entry_id: string | null
  active_index: number | null
  active_count: number
  verified_center_frequency_hz: number | null
  dwell_duration_seconds: number | null
  remaining_dwell_seconds: number | null
  last_error: string | null
}

export interface SpectrumFrame {
  sequence: number
  timestamp: number
  deviceTimestampNs?: bigint
  hostTimestampNs?: bigint
  source?: AnalyzerSourceType
  startHz: number
  centerHz?: number
  stopHz: number
  spanHz?: number
  rbwHz?: number
  referenceLevelDbm?: number
  configurationGeneration: number
  values: Float32Array
  intervalMaxValues?: Float32Array
  intervalStartMonotonicNs?: bigint
  intervalEndMonotonicNs?: bigint
  tracesIntegrated?: number
  scaleToDbm?: number
  offsetToDbm?: number
  waterfall: Uint8Array
}

export interface WaterfallBatch {
  sequence: number
  batchSequence: number
  firstRowSequence: number
  rowCount: number
  pointCount: number
  nominalRowPeriodNs: bigint
  source: AnalyzerSourceType
  deviceTimestampNs: bigint
  hostTimestampNs: bigint
  startHz: number
  centerHz: number
  stopHz: number
  spanHz: number
  rbwHz: number
  referenceLevelDbm: number
  configurationGeneration: number
  values: Uint8Array
}

export type WaterfallFrame = WaterfallBatch

export interface AnalyzerRuntimeStatus {
  source: AnalyzerSourceType
  connected: boolean
  acquisition_running: boolean
  if_overflow: boolean
  amplitude_offset_db?: number
  sdk_frames_per_second: number
  point_count: number | null
  spectrum_publish_fps: number
  spectrum_render_fps?: number
  webgl_target_fps?: number
  waterfall_publish_fps: number
  waterfall_rows_per_second?: number
  waterfall_batches_per_second?: number
  waterfall_rows_per_batch?: number
  waterfall_batches_published?: number
  replaced_display_snapshots: number
  acquisition_errors: number
  last_error: string | null
  reconfiguring: boolean
  configuration_generation: number
  waterfall_raw_scale_db?: number | null
  waterfall_raw_offset_dbm?: number | null
  invalid_frames: number
  timeouts: number
  actualRbwHz?: number
  actual_rbw_hz?: number | null
  requested_rbw_hz?: number | null
  rbw_mode?: 'auto' | 'manual' | null
  fft_size?: number | null
  frequency_bin_spacing_hz?: number | null
  measured_profile_trace_rate_hz?: number | null
  traces_per_spectrum_frame?: number | null
  traces_per_waterfall_row?: number | null
  visible_time_span_seconds?: number
  visible_rows?: number
  resolution_tradeoff_index?: number | null
  resolution_tradeoff_state?: 'auto' | 'matched' | 'custom'
  resolution_tradeoff_step_id?: string | null
  frequency_scan?: FrequencyScanStatus
  playback?: PlaybackStatus
}

export interface Viewport {
  start: number
  end: number
  minDbm: number
  maxDbm: number
}
