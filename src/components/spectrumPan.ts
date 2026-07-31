import type { CenterFrequencyLimits } from '../data/centerFrequencyControl'

export const PAN_MINIMUM_DRAG_PX = 4
export const PAN_TUNE_TIMEOUT_MS = 5_000

export interface SpectrumPanCalculation {
  rawTargetCenterHz: number
  targetCenterHz: number
  effectiveDeltaX: number
  frequencyDeltaHz: number
  clamped: boolean
}

export function safeCenterFrequencyLimits(
  deviceLimits: CenterFrequencyLimits,
  actualSpanHz: number,
): CenterFrequencyLimits {
  const halfSpan = actualSpanHz / 2
  const minimumHz = deviceLimits.minimumHz + halfSpan
  const maximumHz = deviceLimits.maximumHz - halfSpan
  if (maximumHz < minimumHz) return deviceLimits
  return { minimumHz, maximumHz }
}

export function calculateSpectrumPan(
  startCenterHz: number,
  deltaX: number,
  plotWidthPx: number,
  actualSpanHz: number,
  deviceLimits: CenterFrequencyLimits,
): SpectrumPanCalculation {
  if (
    !Number.isFinite(startCenterHz)
    || !Number.isFinite(deltaX)
    || !Number.isFinite(plotWidthPx)
    || plotWidthPx <= 0
    || !Number.isFinite(actualSpanHz)
    || actualSpanHz <= 0
  ) {
    throw new Error('Invalid Spectrum Pan geometry')
  }
  const limits = safeCenterFrequencyLimits(deviceLimits, actualSpanHz)
  const rawTargetCenterHz =
    startCenterHz - (deltaX / plotWidthPx) * actualSpanHz
  const targetCenterHz = Math.min(
    limits.maximumHz,
    Math.max(limits.minimumHz, rawTargetCenterHz),
  )
  const frequencyDeltaHz = targetCenterHz - startCenterHz
  return {
    rawTargetCenterHz,
    targetCenterHz,
    effectiveDeltaX: -(frequencyDeltaHz / actualSpanHz) * plotWidthPx,
    frequencyDeltaHz,
    clamped: targetCenterHz !== rawTargetCenterHz,
  }
}

export function shouldCommitSpectrumPan(
  deltaX: number,
  calculation: SpectrumPanCalculation,
  plotWidthPx: number,
  actualSpanHz: number,
  minimumDragPx = PAN_MINIMUM_DRAG_PX,
) {
  const onePixelHz = actualSpanHz / plotWidthPx
  return Math.abs(deltaX) >= minimumDragPx
    && Math.abs(calculation.frequencyDeltaHz) >= onePixelHz
}

export function formatPanFrequency(frequencyHz: number) {
  if (Math.abs(frequencyHz) >= 1e9)
    return `${Number((frequencyHz / 1e9).toFixed(9))} GHz`
  if (Math.abs(frequencyHz) >= 1e6)
    return `${Number((frequencyHz / 1e6).toFixed(6))} MHz`
  return `${Math.round(frequencyHz)} Hz`
}

export function formatPanDelta(frequencyHz: number) {
  const sign = frequencyHz >= 0 ? '+' : '−'
  const magnitude = Math.abs(frequencyHz)
  if (magnitude >= 1e6)
    return `${sign}${Number((magnitude / 1e6).toFixed(3))} MHz`
  if (magnitude >= 1e3)
    return `${sign}${Number((magnitude / 1e3).toFixed(3))} kHz`
  return `${sign}${Math.round(magnitude)} Hz`
}
