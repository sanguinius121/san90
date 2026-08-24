export interface AiReviewStatus {
  available: boolean
  reason: string | null
  sequence: number | null
  timestamp_ns: number | null
  width: number
  height: number
  center_frequency_hz: number | null
  frequency_start_hz: number | null
  frequency_stop_hz: number | null
  content_type: string
  detection_count: number
  received_at_ns: number | null
  power_min_dbm: number | null
  power_max_dbm: number | null
  power_range_db: number | null
  db_per_gray_level: number | null
  power_range_generation: number | null
}

export interface AiReviewSaveStatus {
  active: boolean
  saved_count: number
  last_saved_path: string | null
  last_error: string | null
}
