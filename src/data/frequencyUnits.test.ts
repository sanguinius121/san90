import { describe, expect, it } from 'vitest'
import {
  centerFrequencyPrecision,
  displayValueToHz,
  hzToDisplayValue,
} from './frequencyUnits'

describe('center-frequency display units', () => {
  it('converts GHz and MHz display values to the same canonical Hz value', () => {
    expect(displayValueToHz(2.45, 'GHz')).toBe(2_450_000_000)
    expect(displayValueToHz(2450, 'MHz')).toBe(2_450_000_000)
  })

  it('preserves one-Hz display precision in both units', () => {
    const hz = 2_450_123_456
    expect(hzToDisplayValue(hz, 'GHz')).toBe(2.450123456)
    expect(hzToDisplayValue(hz, 'MHz')).toBe(2450.123456)
    expect(centerFrequencyPrecision('GHz')).toBe(9)
    expect(centerFrequencyPrecision('MHz')).toBe(6)
  })
})
