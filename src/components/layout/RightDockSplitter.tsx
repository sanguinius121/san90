import { useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { RightDockLimits } from '../../hooks/useResizableRightDock'

interface RightDockSplitterProps {
  width: number
  limits: RightDockLimits
  onBeginDrag: (clientX: number) => void
  onMoveDrag: (clientX: number) => void
  onEndDrag: () => void
  onCancelDrag: () => void
  onResizeBy: (delta: number) => void
  onMinimum: () => void
  onMaximum: () => void
}

export function RightDockSplitter({
  width,
  limits,
  onBeginDrag,
  onMoveDrag,
  onEndDrag,
  onCancelDrag,
  onResizeBy,
  onMinimum,
  onMaximum,
}: RightDockSplitterProps) {
  const [active, setActive] = useState(false)

  const begin = (event: PointerEvent<HTMLDivElement>) => {
    if (limits.maximum <= 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setActive(true)
    onBeginDrag(event.clientX)
  }
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (active) onMoveDrag(event.clientX)
  }
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    if (!active) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setActive(false)
    onEndDrag()
  }
  const cancel = (event: PointerEvent<HTMLDivElement>) => {
    if (!active) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setActive(false)
    onCancelDrag()
  }
  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 50 : 10
    if (event.key === 'ArrowLeft') onResizeBy(step)
    else if (event.key === 'ArrowRight') onResizeBy(-step)
    else if (event.key === 'Home') onMinimum()
    else if (event.key === 'End') onMaximum()
    else if (event.key === 'Escape' && active) {
      setActive(false)
      onCancelDrag()
    } else return
    event.preventDefault()
  }

  return (
    <div
      className={`right-dock-splitter ${active ? 'is-active' : ''}`}
      role="separator"
      aria-label="Resize right dock"
      aria-orientation="vertical"
      aria-valuemin={limits.minimum}
      aria-valuemax={limits.maximum}
      aria-valuenow={Math.round(width)}
      aria-disabled={limits.maximum <= limits.minimum}
      tabIndex={0}
      onPointerDown={begin}
      onPointerMove={move}
      onPointerUp={finish}
      onPointerCancel={cancel}
      onKeyDown={keyDown}
    />
  )
}
