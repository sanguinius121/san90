export interface AiPreviewStatus {
  available: boolean
  reason: string | null
  sequence: number | null
  source: 'hardware' | 'simulator' | 'playback' | string
  playback_epoch: number | null
  config_id: number | null
  configuration_generation: number | null
  center_frequency_hz: number | null
  frequency_start_hz: number | null
  frequency_stop_hz: number | null
  width: number
  height: number
  created_at_ns: number | null
  content_type: string
}
