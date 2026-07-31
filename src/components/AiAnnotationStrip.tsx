import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { aiDetections } from '../data/aiDetections'
import { liveFrames } from '../data/liveFrames'
import { useDeviceStore, useDisplayStore } from '../stores'
import { sharedHorizontalPlotRect } from '../rendering/plotGeometry'
import {
  AI_DETECTION_HOLD_MS,
  confidenceBand,
  mapDetectionToPlot,
  mergeHeldDetections,
  placeDetectionsInLanes,
  type HeldAiDetection,
  type MappedAiDetection,
} from './aiAnnotationLayout'

const ONE_LANE_HEIGHT = 30
const TWO_LANE_HEIGHT = 46
const LANE_BOX_HEIGHT = 17

function formatFrequency(frequencyHz: number) {
  if (frequencyHz >= 1e9) return `${(frequencyHz / 1e9).toFixed(6)} GHz`
  if (frequencyHz >= 1e6) return `${(frequencyHz / 1e6).toFixed(3)} MHz`
  return `${frequencyHz.toFixed(0)} Hz`
}

export function AiAnnotationStrip() {
  const rootRef = useRef<HTMLDivElement>(null)
  const clipId = `ai-strip-${useId().replace(/:/g, '')}`
  const initial = liveFrames.getLatest()
  const centerHz = useDeviceStore((state) => state.centerHz)
  const spanHz = useDeviceStore((state) => state.spanHz)
  const viewport = useDisplayStore((state) => state.viewport)
  const panPhase = useDisplayStore((state) => state.panPhase)
  const [width, setWidth] = useState(1)
  const [range, setRange] = useState(() => ({
    startHz: initial?.startHz ?? centerHz - spanHz / 2,
    stopHz: initial?.stopHz ?? centerHz + spanHz / 2,
  }))
  const [held, setHeld] = useState<HeldAiDetection[]>([])

  useEffect(() => {
    const element = rootRef.current
    if (!element) return
    const update = () => setWidth(Math.max(1, element.clientWidth))
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const unsubscribe = liveFrames.subscribe((frame) => {
      setRange((previous) => (
        previous.startHz === frame.startHz && previous.stopHz === frame.stopHz
          ? previous
          : { startHz: frame.startHz, stopHz: frame.stopHz }
      ))
    })
    return () => {
      unsubscribe()
    }
  }, [])

  useEffect(() => {
    const unsubscribe = aiDetections.subscribe((result) => {
      const now = Date.now()
      setHeld((previous) => mergeHeldDetections(previous, result, now))
    })
    const unsubscribeClear = aiDetections.subscribeClear(() => setHeld([]))
    return () => {
      unsubscribe()
      unsubscribeClear()
    }
  }, [])

  useEffect(() => {
    if (!held.length) return
    const delay = Math.max(0, Math.min(...held.map((item) => item.expiresAtMs)) - Date.now())
    const timer = window.setTimeout(() => {
      const now = Date.now()
      setHeld((current) => current.filter((item) => item.expiresAtMs > now))
    }, delay + 1)
    return () => window.clearTimeout(timer)
  }, [held])

  const rect = useMemo(() => sharedHorizontalPlotRect(width), [width])
  const mapped = useMemo(() => placeDetectionsInLanes(held)
    .map((detection) => mapDetectionToPlot(detection, range.startHz, range.stopHz, viewport, rect))
    .filter((detection): detection is MappedAiDetection => detection !== null), [
    held,
    range,
    viewport,
    rect,
  ])
  const hasSecondLane = mapped.some((detection) => detection.lane === 1)
  const height = hasSecondLane ? TWO_LANE_HEIGHT : ONE_LANE_HEIGHT

  return (
    <div
      ref={rootRef}
      className="ai-annotation-strip"
      style={{ height }}
      data-lanes={hasSecondLane ? 2 : 1}
      aria-label="Current AI frequency annotations"
    >
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <defs>
          <clipPath id={clipId}>
            <rect x={rect.left} y={0} width={rect.width} height={height} />
          </clipPath>
        </defs>
        <g
          clipPath={`url(#${clipId})`}
          opacity={panPhase === 'dragging' || panPhase === 'tuning' ? 0 : 1}
          aria-hidden={panPhase === 'dragging' || panPhase === 'tuning'}
        >
          {mapped.map((detection) => {
            const y = hasSecondLane ? 3 + detection.lane * 20 : 6
            const rangeWidth = Math.max(0.5, detection.xStop - detection.xStart)
            const text = `${detection.label} ${Math.round(detection.confidence * 100)}%`
            const textWidth = Math.min(rect.width, Math.max(58, text.length * 6.4 + 10))
            const labelX = rangeWidth >= textWidth
              ? detection.xStart + (rangeWidth - textWidth) / 2
              : Math.max(rect.left, Math.min(detection.xStart, rect.right - textWidth))
            const sourceAgeMs = detection.receivedAtNs == null
              ? null
              : Math.max(
                0,
                detection.expiresAtMs - AI_DETECTION_HOLD_MS - detection.receivedAtNs / 1e6,
              )
            const tooltip = [
              detection.label,
              `${Math.round(detection.confidence * 100)}% confidence`,
              `${formatFrequency(detection.frequencyStartHz)} – ${formatFrequency(detection.frequencyStopHz)}`,
              detection.source === 'playback'
                ? 'Playback AI'
                : detection.source == null
                  ? null
                  : 'Realtime AI',
              sourceAgeMs == null ? null : `${Math.round(sourceAgeMs)} ms old at receipt`,
            ].filter(Boolean).join(' · ')
            const band = confidenceBand(detection.confidence)
            return (
              <g key={detection.id} className={`ai-annotation ai-annotation--${band}`}>
                <title>{tooltip}</title>
                <rect className="ai-annotation__range" x={detection.xStart} y={y} width={rangeWidth} height={LANE_BOX_HEIGHT} />
                <rect className="ai-annotation__label-bg" x={labelX} y={y + 1} width={textWidth} height={LANE_BOX_HEIGHT - 2} rx={2} />
                <text x={labelX + textWidth / 2} y={y + LANE_BOX_HEIGHT / 2}>{text}</text>
                <line x1={detection.xStart} y1={y} x2={detection.xStart} y2={y + LANE_BOX_HEIGHT} />
                <line x1={detection.xStop} y1={y} x2={detection.xStop} y2={y + LANE_BOX_HEIGHT} />
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}
