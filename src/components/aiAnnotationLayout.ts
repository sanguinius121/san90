import { frequencyToPlotX, type HorizontalPlotRect } from '../rendering/plotGeometry'
import type { AiDetectionResult, AiFrequencyDetection } from '../types'

export const AI_DETECTION_HOLD_MS = 800

export interface HeldAiDetection extends AiFrequencyDetection {
  id: string
  expiresAtMs: number
  receivedAtNs: number | null
  source?: AiDetectionResult['source']
}

export interface PlacedAiDetection extends HeldAiDetection {
  lane: 0 | 1
}

export interface MappedAiDetection extends PlacedAiDetection {
  xStart: number
  xStop: number
}

function overlapHz(a: AiFrequencyDetection, b: AiFrequencyDetection) {
  return Math.max(0, Math.min(a.frequencyStopHz, b.frequencyStopHz) - Math.max(a.frequencyStartHz, b.frequencyStartHz))
}

function isMatchingDetection(a: AiFrequencyDetection, b: AiFrequencyDetection) {
  if (a.label !== b.label) return false
  const overlap = overlapHz(a, b)
  const minimumWidth = Math.min(
    a.frequencyStopHz - a.frequencyStartHz,
    b.frequencyStopHz - b.frequencyStartHz,
  )
  return minimumWidth > 0 && overlap / minimumWidth >= 0.5
}

export function mergeHeldDetections(
  previous: HeldAiDetection[],
  result: AiDetectionResult,
  nowMs: number,
  holdMs = AI_DETECTION_HOLD_MS,
): HeldAiDetection[] {
  const current = previous.filter((item) => item.expiresAtMs > nowMs)
  const used = new Set<string>()
  const incoming = [...result.detections].sort((a, b) => (
    a.frequencyStartHz - b.frequencyStartHz ||
    b.confidence - a.confidence ||
    a.label.localeCompare(b.label)
  ))
  const refreshed = incoming.map((detection, index) => {
    const match = current
      .filter((item) => !used.has(item.id) && isMatchingDetection(item, detection))
      .sort((a, b) => overlapHz(b, detection) - overlapHz(a, detection) || a.id.localeCompare(b.id))[0]
    if (match) used.add(match.id)
    return {
      ...detection,
      id: match?.id ?? `${result.sequence ?? result.timestampNs ?? nowMs}:${index}:${detection.label}:${detection.frequencyStartHz}`,
      expiresAtMs: nowMs + holdMs,
      receivedAtNs: result.receivedAtNs,
      source: result.source,
    }
  })
  return [
    ...current.filter((item) => !used.has(item.id)),
    ...refreshed,
  ].sort((a, b) => a.frequencyStartHz - b.frequencyStartHz || b.confidence - a.confidence || a.id.localeCompare(b.id))
}

function intervalsOverlap(a: AiFrequencyDetection, b: AiFrequencyDetection) {
  return a.frequencyStartHz < b.frequencyStopHz && b.frequencyStartHz < a.frequencyStopHz
}

export function placeDetectionsInLanes(detections: HeldAiDetection[]): PlacedAiDetection[] {
  const lanes: HeldAiDetection[][] = [[], []]
  const prioritized = [...detections].sort((a, b) => (
    b.confidence - a.confidence ||
    a.frequencyStartHz - b.frequencyStartHz ||
    a.frequencyStopHz - b.frequencyStopHz ||
    a.label.localeCompare(b.label) ||
    a.id.localeCompare(b.id)
  ))
  const placed: PlacedAiDetection[] = []
  for (const detection of prioritized) {
    const lane = lanes.findIndex((items) => items.every((item) => !intervalsOverlap(item, detection)))
    if (lane < 0) continue
    lanes[lane].push(detection)
    placed.push({ ...detection, lane: lane as 0 | 1 })
  }
  return placed.sort((a, b) => (
    a.frequencyStartHz - b.frequencyStartHz ||
    a.lane - b.lane ||
    b.confidence - a.confidence ||
    a.id.localeCompare(b.id)
  ))
}

export function mapDetectionToPlot(
  detection: PlacedAiDetection,
  sourceStartHz: number,
  sourceStopHz: number,
  viewport: { start: number; end: number },
  rect: HorizontalPlotRect,
): MappedAiDetection | null {
  const sourceSpan = sourceStopHz - sourceStartHz
  const visibleStartHz = sourceStartHz + sourceSpan * viewport.start
  const visibleStopHz = sourceStartHz + sourceSpan * viewport.end
  const clippedStart = Math.max(detection.frequencyStartHz, visibleStartHz)
  const clippedStop = Math.min(detection.frequencyStopHz, visibleStopHz)
  if (clippedStop <= clippedStart) return null
  return {
    ...detection,
    xStart: frequencyToPlotX(clippedStart, visibleStartHz, visibleStopHz, rect),
    xStop: frequencyToPlotX(clippedStop, visibleStartHz, visibleStopHz, rect),
  }
}

export function confidenceBand(confidence: number): 'low' | 'medium' | 'high' {
  if (confidence < 0.5) return 'low'
  if (confidence <= 0.75) return 'medium'
  return 'high'
}
