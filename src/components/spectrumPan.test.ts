import { describe, expect, it } from 'vitest'
import {
  calculateSpectrumPan,
  safeCenterFrequencyLimits,
  shouldCommitSpectrumPan,
} from './spectrumPan'

const limits = { minimumHz: 1e6, maximumHz: 9.5e9 }

describe('Spectrum Pan frequency mapping', () => {
  it('increases center when the trace is dragged left', () => {
    const result = calculateSpectrumPan(2.45e9, -100, 1000, 100e6, limits)
    expect(result.targetCenterHz).toBe(2.46e9)
    expect(result.effectiveDeltaX).toBe(-100)
  })

  it('decreases center when the trace is dragged right', () => {
    const result = calculateSpectrumPan(2.45e9, 100, 1000, 100e6, limits)
    expect(result.targetCenterHz).toBe(2.44e9)
    expect(result.effectiveDeltaX).toBe(100)
  })

  it('maps a half-plot drag to half the verified span', () => {
    expect(
      calculateSpectrumPan(2.45e9, -400, 800, 101.5625e6, limits)
        .frequencyDeltaHz,
    ).toBe(50.78125e6)
  })

  it('uses the drawable plot width supplied by the caller', () => {
    const plotWidth = calculateSpectrumPan(
      2.45e9,
      -100,
      800,
      100e6,
      limits,
    )
    const fullCanvasWidth = calculateSpectrumPan(
      2.45e9,
      -100,
      1000,
      100e6,
      limits,
    )
    expect(plotWidth.frequencyDeltaHz).toBe(12.5e6)
    expect(fullCanvasWidth.frequencyDeltaHz).toBe(10e6)
  })

  it('clamps center so both span edges remain within device limits', () => {
    const safe = safeCenterFrequencyLimits(
      { minimumHz: 100e6, maximumHz: 1e9 },
      100e6,
    )
    expect(safe).toEqual({ minimumHz: 150e6, maximumHz: 950e6 })
    expect(
      calculateSpectrumPan(
        200e6,
        1000,
        100,
        100e6,
        { minimumHz: 100e6, maximumHz: 1e9 },
      ),
    ).toMatchObject({ targetCenterHz: 150e6, clamped: true })
    expect(
      calculateSpectrumPan(
        900e6,
        -1000,
        100,
        100e6,
        { minimumHz: 100e6, maximumHz: 1e9 },
      ),
    ).toMatchObject({ targetCenterHz: 950e6, clamped: true })
  })

  it('rejects clicks and sub-pixel frequency moves', () => {
    const calculation = calculateSpectrumPan(
      2.45e9,
      -3,
      1000,
      100e6,
      limits,
    )
    expect(
      shouldCommitSpectrumPan(3, calculation, 1000, 100e6),
    ).toBe(false)
    expect(
      shouldCommitSpectrumPan(4, calculation, 1000, 100e6),
    ).toBe(true)
  })

  it('rejects invalid plot geometry', () => {
    expect(() =>
      calculateSpectrumPan(2.45e9, 10, 0, 100e6, limits),
    ).toThrow(/geometry/)
  })
})
