export type RecordingMode = 'fixed' | 'manual'

export type RecordingState =
  | 'idle'
  | 'starting'
  | 'recording'
  | 'stopping'
  | 'finalizing'
  | 'completed'
  | 'failed'

export type RecordingStopReason =
  | 'user_stop'
  | 'fixed_duration'
  | 'file_size_limit'
  | 'low_disk'
  | 'writer_overrun'
  | 'device_disconnect'
  | 'backend_shutdown'
  | 'writer_error'
  | 'start_failure'

export interface RecordingConfig {
  version: number
  mode: RecordingMode
  duration_s: number | null
  file_size_limit_bytes: number
  free_disk_reserve_bytes: number
  output_directory: string
  file_prefix: string
  recording_root: string
  load_warning: string | null
  save_error: string | null
}

export interface RecordingConfigUpdate {
  mode: RecordingMode
  duration_s: number | null
  file_size_limit_bytes: number
  free_disk_reserve_bytes: number
  output_directory: string
  file_prefix: string
}

export interface RecordingDirectoryList {
  root_name: string
  directories: string[]
  created: string | null
}

export interface RecordingStatus {
  state: RecordingState
  session_uuid: string | null
  part_file_path: string | null
  final_file_path: string | null
  mode: RecordingMode | null
  elapsed_s: number
  written_bytes: number
  trace_count: number
  batch_count: number
  gap_count: number
  lost_trace_count: number
  queue_bytes: number
  queue_items: number
  queue_fill_ratio: number
  queue_item_fill_ratio: number
  queue_high_water_bytes: number
  queue_high_water_items: number
  enqueued_batches: number
  written_batches: number
  rejected_batches: number
  rejected_traces: number
  rejected_samples: number
  write_rate_bytes_s: number
  last_write_latency_ms: number
  stop_reason: RecordingStopReason | null
  last_error: string | null
  active_config_id: number | null
  active_configuration_generation: number | null
  source: 'san90' | 'simulator'
  queue_pressure: 'normal' | 'warning' | 'critical'
  available_disk_bytes: number | null
  total_disk_bytes: number | null
}
