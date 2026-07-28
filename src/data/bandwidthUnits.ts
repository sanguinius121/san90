export type BandwidthUnit = 'Hz' | 'kHz' | 'MHz'

export const BANDWIDTH_UNITS: readonly BandwidthUnit[] = ['Hz', 'kHz', 'MHz']

const HZ_PER_UNIT: Record<BandwidthUnit, number> = {
  Hz: 1,
  kHz: 1e3,
  MHz: 1e6,
}

export function bandwidthDisplayToHz(value: number, unit: BandwidthUnit): number {
  return value * HZ_PER_UNIT[unit]
}

export function hzToBandwidthDisplay(hz: number, unit: BandwidthUnit): number {
  return hz / HZ_PER_UNIT[unit]
}

export function bandwidthPrecision(unit: BandwidthUnit): number {
  return unit === 'MHz' ? 9 : unit === 'kHz' ? 6 : 3
}

export function compactBandwidthUnit(hz: number): BandwidthUnit {
  return Math.abs(hz) >= 1e6 ? 'MHz' : Math.abs(hz) >= 1e3 ? 'kHz' : 'Hz'
}
