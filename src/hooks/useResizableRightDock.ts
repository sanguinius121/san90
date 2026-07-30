import { useCallback, useLayoutEffect, useRef, useState } from 'react'

export const RIGHT_DOCK_STORAGE_KEY = 'san90.layout.rightDockWidth'
export const RIGHT_DOCK_DEFAULT_WIDTH = 418
export const RIGHT_DOCK_MIN_WIDTH = 398
export const RIGHT_DOCK_MAX_WIDTH = 778
export const LAYOUT_SPLITTER_WIDTH = 6
export const MEASUREMENT_MIN_WIDTH = 640

export interface RightDockLimits {
  minimum: number
  maximum: number
  constrained: boolean
}

export function rightDockLimits(viewportWidth: number): RightDockLimits {
  const available = Math.max(0, Math.floor(viewportWidth) - MEASUREMENT_MIN_WIDTH - LAYOUT_SPLITTER_WIDTH)
  const maximum = Math.min(RIGHT_DOCK_MAX_WIDTH, available)
  return {
    minimum: Math.min(RIGHT_DOCK_MIN_WIDTH, maximum),
    maximum,
    constrained: maximum < RIGHT_DOCK_MIN_WIDTH,
  }
}

export function clampRightDockWidth(width: number, limits: RightDockLimits): number {
  return Math.min(limits.maximum, Math.max(limits.minimum, width))
}

function restoredWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(RIGHT_DOCK_STORAGE_KEY))
    return Number.isFinite(stored) && stored > 0 ? stored : RIGHT_DOCK_DEFAULT_WIDTH
  } catch {
    return RIGHT_DOCK_DEFAULT_WIDTH
  }
}

export function useResizableRightDock(rootRef: React.RefObject<HTMLElement | null>) {
  const initialPreferred = useRef(restoredWidth())
  const preferredWidth = useRef(initialPreferred.current)
  const limitsRef = useRef(rightDockLimits(window.innerWidth))
  const widthRef = useRef(clampRightDockWidth(preferredWidth.current, limitsRef.current))
  const pendingWidth = useRef<number | null>(null)
  const animationFrame = useRef<number | null>(null)
  const dragStart = useRef<{ x: number; width: number } | null>(null)
  const [width, setWidth] = useState(widthRef.current)
  const [limits, setLimits] = useState(limitsRef.current)

  const applyWidth = useCallback((next: number) => {
    const clamped = clampRightDockWidth(next, limitsRef.current)
    widthRef.current = clamped
    rootRef.current?.style.setProperty('--right-dock-width', `${clamped}px`)
    return clamped
  }, [rootRef])

  const flushPending = useCallback(() => {
    animationFrame.current = null
    if (pendingWidth.current !== null) {
      applyWidth(pendingWidth.current)
      pendingWidth.current = null
    }
  }, [applyWidth])

  const scheduleWidth = useCallback((next: number) => {
    pendingWidth.current = next
    if (animationFrame.current === null) {
      animationFrame.current = window.requestAnimationFrame(flushPending)
    }
  }, [flushPending])

  const commitWidth = useCallback((next: number) => {
    pendingWidth.current = null
    if (animationFrame.current !== null) {
      window.cancelAnimationFrame(animationFrame.current)
      animationFrame.current = null
    }
    preferredWidth.current = next
    const applied = applyWidth(next)
    setWidth(applied)
    try {
      window.localStorage.setItem(RIGHT_DOCK_STORAGE_KEY, String(next))
    } catch {
      // Layout persistence is optional; resizing must continue without storage.
    }
  }, [applyWidth])

  const beginDrag = useCallback((clientX: number) => {
    dragStart.current = { x: clientX, width: widthRef.current }
  }, [])

  const moveDrag = useCallback((clientX: number) => {
    const start = dragStart.current
    if (start !== null) scheduleWidth(start.width + start.x - clientX)
  }, [scheduleWidth])

  const endDrag = useCallback(() => {
    if (dragStart.current === null) return
    const next = pendingWidth.current ?? widthRef.current
    dragStart.current = null
    commitWidth(clampRightDockWidth(next, limitsRef.current))
  }, [commitWidth])

  const cancelDrag = useCallback(() => {
    const start = dragStart.current
    if (start === null) return
    dragStart.current = null
    pendingWidth.current = null
    if (animationFrame.current !== null) {
      window.cancelAnimationFrame(animationFrame.current)
      animationFrame.current = null
    }
    const restored = applyWidth(start.width)
    setWidth(restored)
  }, [applyWidth])

  const resizeBy = useCallback((delta: number) => {
    commitWidth(widthRef.current + delta)
  }, [commitWidth])

  const setToMinimum = useCallback(() => commitWidth(limitsRef.current.minimum), [commitWidth])
  const setToMaximum = useCallback(() => commitWidth(limitsRef.current.maximum), [commitWidth])
  const reset = useCallback(() => {
    preferredWidth.current = RIGHT_DOCK_DEFAULT_WIDTH
    try {
      window.localStorage.removeItem(RIGHT_DOCK_STORAGE_KEY)
    } catch {
      // The default still applies when storage is unavailable.
    }
    const applied = applyWidth(RIGHT_DOCK_DEFAULT_WIDTH)
    setWidth(applied)
  }, [applyWidth])

  useLayoutEffect(() => {
    applyWidth(widthRef.current)
    const onResize = () => {
      const nextLimits = rightDockLimits(window.innerWidth)
      limitsRef.current = nextLimits
      setLimits(nextLimits)
      const applied = applyWidth(preferredWidth.current)
      setWidth(applied)
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      if (animationFrame.current !== null) window.cancelAnimationFrame(animationFrame.current)
      dragStart.current = null
    }
  }, [applyWidth])

  return {
    width,
    limits,
    dragging: dragStart.current !== null,
    beginDrag,
    moveDrag,
    endDrag,
    cancelDrag,
    resizeBy,
    setToMinimum,
    setToMaximum,
    reset,
  }
}
