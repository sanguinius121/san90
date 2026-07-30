// @vitest-environment jsdom

import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { aiDetections } from '../data/aiDetections'
import { liveFrames } from '../data/liveFrames'
import { frequencyToPlotX, sharedHorizontalPlotRect } from '../rendering/plotGeometry'
import type { AiDetectionResult } from '../types'
import {
  confidenceBand,
  mapDetectionToPlot,
  mergeHeldDetections,
  placeDetectionsInLanes,
  type HeldAiDetection,
} from './aiAnnotationLayout'
import { AiAnnotationStrip } from './AiAnnotationStrip'

const held = (
  id: string,
  start: number,
  stop: number,
  confidence: number,
  label = id,
): HeldAiDetection => ({
  id,
  label,
  confidence,
  frequencyStartHz: start,
  frequencyStopHz: stop,
  expiresAtMs: 10_000,
  receivedAtNs: null,
})

const result = (detections: AiDetectionResult['detections']): AiDetectionResult => ({
  source: 'playback',
  sequence: 7,
  timestampNs: 1_000_000_000,
  generatedAt: 1,
  receivedAtNs: 1_000_000_100,
  detections,
})

afterEach(() => {
  cleanup()
  aiDetections.clear()
  liveFrames.clear()
  vi.useRealTimers()
})

describe('AI annotation behavior', () => {
  it('uses blue, yellow, and red confidence thresholds', () => {
    expect(confidenceBand(0.49)).toBe('low')
    expect(confidenceBand(0.5)).toBe('medium')
    expect(confidenceBand(0.75)).toBe('medium')
    expect(confidenceBand(0.751)).toBe('high')
  })

  it('expires stale detections and refreshes a matching detection', () => {
    const first = mergeHeldDetections([], result([{
      label: 'ELRS', confidence: 0.7, frequencyStartHz: 900e6, frequencyStopHz: 920e6,
    }]), 100, 800)
    const refreshed = mergeHeldDetections(first, result([{
      label: 'ELRS', confidence: 0.8, frequencyStartHz: 901e6, frequencyStopHz: 921e6,
    }]), 700, 800)
    expect(refreshed).toHaveLength(1)
    expect(refreshed[0].id).toBe(first[0].id)
    expect(refreshed[0].expiresAtMs).toBe(1500)
    expect(mergeHeldDetections(refreshed, result([]), 1501, 800)).toHaveLength(0)
  })

  it('uses two lanes and prioritizes confidence when three ranges overlap', () => {
    const placed = placeDetectionsInLanes([
      held('low', 100, 200, 0.4),
      held('high', 100, 200, 0.9),
      held('medium', 100, 200, 0.7),
    ])
    expect(placed).toHaveLength(2)
    expect(new Set(placed.map((item) => item.lane))).toEqual(new Set([0, 1]))
    expect(placed.map((item) => item.id).sort()).toEqual(['high', 'medium'])
  })

  it('maps annotation edges with the shared plot transform after range changes', () => {
    const detection = { ...held('signal', 2.44e9, 2.46e9, 0.9), lane: 0 as const }
    const rect = sharedHorizontalPlotRect(1000)
    const mapped = mapDetectionToPlot(detection, 2.4e9, 2.5e9, { start: 0, end: 1 }, rect)
    expect(mapped?.xStart).toBeCloseTo(frequencyToPlotX(2.44e9, 2.4e9, 2.5e9, rect))
    expect(mapped?.xStop).toBeCloseTo(frequencyToPlotX(2.46e9, 2.4e9, 2.5e9, rect))
    const retuned = mapDetectionToPlot(detection, 2.43e9, 2.48e9, { start: 0, end: 1 }, rect)
    expect(retuned?.xStart).toBeCloseTo(frequencyToPlotX(2.44e9, 2.43e9, 2.48e9, rect))
    expect(retuned?.xStart).not.toBeCloseTo(mapped?.xStart ?? 0)
  })

  it('renders compact label text and removes it after the hold period', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-25T00:00:00Z'))
    liveFrames.publish({
      sequence: 1,
      timestamp: Date.now(),
      source: 'san90',
      configurationGeneration: 1,
      startHz: 2.4e9,
      centerHz: 2.45e9,
      stopHz: 2.5e9,
      spanHz: 100e6,
      values: new Float32Array(2),
      waterfall: new Uint8Array(),
    })
    const { container } = render(<AiAnnotationStrip />)
    act(() => aiDetections.publish(result([
      { label: 'LOW', confidence: 0.4, frequencyStartHz: 2.41e9, frequencyStopHz: 2.42e9 },
      { label: 'MID', confidence: 0.6, frequencyStartHz: 2.43e9, frequencyStopHz: 2.44e9 },
      { label: 'DJI_20MHz', confidence: 0.86, frequencyStartHz: 2.46e9, frequencyStopHz: 2.48e9 },
    ])))
    expect(screen.getByText('DJI_20MHz 86%')).toBeTruthy()
    expect(container.querySelector('title')?.textContent).toContain('Playback AI')
    expect(container.querySelector('.ai-annotation--low')).toBeTruthy()
    expect(container.querySelector('.ai-annotation--medium')).toBeTruthy()
    expect(container.querySelector('.ai-annotation--high')).toBeTruthy()
    const strip = container.querySelector('.ai-annotation-strip') as HTMLElement
    expect(strip.getAttribute('data-lanes')).toBe('1')
    expect(strip.style.height).toBe('30px')
    act(() => vi.advanceTimersByTime(801))
    expect(screen.queryByText('DJI_20MHz 86%')).toBeNull()
  })

  it('grows to 46px only when overlapping annotations need the second lane', () => {
    liveFrames.publish({
      sequence: 1,
      timestamp: Date.now(),
      source: 'san90',
      configurationGeneration: 1,
      startHz: 900e6,
      centerHz: 915e6,
      stopHz: 930e6,
      spanHz: 30e6,
      values: new Float32Array(2),
      waterfall: new Uint8Array(),
    })
    const { container } = render(<AiAnnotationStrip />)
    act(() => aiDetections.publish(result([
      { label: 'FHSS_A', confidence: 0.9, frequencyStartHz: 905e6, frequencyStopHz: 920e6 },
      { label: 'FHSS_B', confidence: 0.8, frequencyStartHz: 910e6, frequencyStopHz: 925e6 },
    ])))
    const strip = container.querySelector('.ai-annotation-strip') as HTMLElement
    expect(strip.getAttribute('data-lanes')).toBe('2')
    expect(strip.style.height).toBe('46px')
  })
})
