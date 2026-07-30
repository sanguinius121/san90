export type PlaybackState =
  | 'idle'
  | 'opening'
  | 'ready'
  | 'playing'
  | 'paused'
  | 'seeking'
  | 'stopping'
  | 'completed'
  | 'failed'

export interface RecordingSummary {
  id: string
  filename: string
  size_bytes: number
  created_at: string | null
  duration_s: number
  trace_count: number
  batch_count: number
  config_count: number
  gap_count: number
  lost_trace_count: number
  stop_reason: string | null
  complete: boolean
  clean: boolean
  playable: boolean
  error: string | null
}

export interface PlaybackStatus {
  state: PlaybackState
  recording_id: string | null
  filename: string | null
  position_s: number
  duration_s: number
  progress: number
  current_sequence: number | null
  current_record_index: number | null
  current_trace_index: number | null
  current_config_id: number | null
  configuration_generation: number | null
  center_frequency_hz: number | null
  point_count: number | null
  gaps_passed: number
  reconfiguration_pauses_passed: number
  lost_traces_passed: number
  auto_loop: boolean
  loop_count: number
  run_ai: boolean
  playback_epoch: number
  ai_warning: string | null
  source: 'playback'
  previous_source: string | null
  last_error: string | null
}
