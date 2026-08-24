export type AiPowerPreset = 'normal' | 'external_lna' | 'strong_signal'

export interface AiPowerRange {
  mode: 'preset' | 'custom'
  preset: AiPowerPreset | null
  power_min_dbm: number
  power_max_dbm: number
  range_db: number
  db_per_gray_level: number
  generation: number
  supported_min_dbm: number
  supported_max_dbm: number
  minimum_range_db: number
}
