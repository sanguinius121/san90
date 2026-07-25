export type CenterFrequencyUnit = 'GHz' | 'MHz'

export const CENTER_FREQUENCY_UNITS: readonly CenterFrequencyUnit[] = ['GHz', 'MHz']

const HZ_PER_UNIT: Record<CenterFrequencyUnit, number> = {
  GHz: 1e9,
  MHz: 1e6,
}

export function displayValueToHz(value: number, unit: CenterFrequencyUnit): number {
  return value * HZ_PER_UNIT[unit]
}

export function hzToDisplayValue(hz: number, unit: CenterFrequencyUnit): number {
  return hz / HZ_PER_UNIT[unit]
}

export function centerFrequencyPrecision(unit: CenterFrequencyUnit): number {
  return unit === 'GHz' ? 9 : 6
}
