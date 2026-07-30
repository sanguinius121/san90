// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRef } from 'react'
import {
  RIGHT_DOCK_DEFAULT_WIDTH,
  RIGHT_DOCK_MAX_WIDTH,
  RIGHT_DOCK_MIN_WIDTH,
  RIGHT_DOCK_STORAGE_KEY,
  useResizableRightDock,
} from '../../hooks/useResizableRightDock'
import { RightDockSplitter } from './RightDockSplitter'

function Harness() {
  const root = useRef<HTMLElement>(null)
  const dock = useResizableRightDock(root)
  return (
    <main ref={root}>
      <RightDockSplitter
        width={dock.width}
        limits={dock.limits}
        onBeginDrag={dock.beginDrag}
        onMoveDrag={dock.moveDrag}
        onEndDrag={dock.endDrag}
        onCancelDrag={dock.cancelDrag}
        onResizeBy={dock.resizeBy}
        onMinimum={dock.setToMinimum}
        onMaximum={dock.setToMaximum}
      />
      <button onClick={dock.reset}>Reset</button>
    </main>
  )
}

let frames: FrameRequestCallback[]

beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1400 })
  frames = []
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
    frames.push(callback)
    return frames.length
  }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: vi.fn() })
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: vi.fn(() => true) })
  Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { configurable: true, value: vi.fn() })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('resizable right dock', () => {
  it('applies the default and restores only a valid stored width', () => {
    const first = render(<Harness />)
    expect(first.container.querySelector('main')?.style.getPropertyValue('--right-dock-width')).toBe(`${RIGHT_DOCK_DEFAULT_WIDTH}px`)
    first.unmount()

    localStorage.setItem(RIGHT_DOCK_STORAGE_KEY, '650')
    const stored = render(<Harness />)
    expect(stored.container.querySelector('main')?.style.getPropertyValue('--right-dock-width')).toBe('650px')
    stored.unmount()

    localStorage.setItem(RIGHT_DOCK_STORAGE_KEY, 'invalid')
    const invalid = render(<Harness />)
    expect(invalid.container.querySelector('main')?.style.getPropertyValue('--right-dock-width')).toBe(`${RIGHT_DOCK_DEFAULT_WIDTH}px`)
  })

  it('throttles pointer moves and persists only after pointerup', () => {
    const { container } = render(<Harness />)
    const root = container.querySelector('main')!
    const splitter = screen.getByRole('separator')
    fireEvent.pointerDown(splitter, { pointerId: 7, clientX: 500 })
    fireEvent.pointerMove(splitter, { pointerId: 7, clientX: 470 })
    fireEvent.pointerMove(splitter, { pointerId: 7, clientX: 450 })
    expect(requestAnimationFrame).toHaveBeenCalledTimes(1)
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('418px')
    expect(localStorage.getItem(RIGHT_DOCK_STORAGE_KEY)).toBeNull()
    frames.shift()?.(0)
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('468px')
    fireEvent.pointerUp(splitter, { pointerId: 7, clientX: 450 })
    expect(localStorage.getItem(RIGHT_DOCK_STORAGE_KEY)).toBe('468')
  })

  it('clamps drag, cancels safely, and supports keyboard controls', () => {
    const { container } = render(<Harness />)
    const root = container.querySelector('main')!
    const splitter = screen.getByRole('separator')
    expect(splitter.getAttribute('aria-orientation')).toBe('vertical')

    fireEvent.keyDown(splitter, { key: 'End' })
    expect(root.style.getPropertyValue('--right-dock-width')).toBe(`${Math.min(RIGHT_DOCK_MAX_WIDTH, 1400 - 640 - 6)}px`)
    fireEvent.keyDown(splitter, { key: 'Home' })
    expect(root.style.getPropertyValue('--right-dock-width')).toBe(`${RIGHT_DOCK_MIN_WIDTH}px`)
    fireEvent.keyDown(splitter, { key: 'ArrowLeft' })
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('408px')
    fireEvent.keyDown(splitter, { key: 'ArrowRight', shiftKey: true })
    expect(root.style.getPropertyValue('--right-dock-width')).toBe(`${RIGHT_DOCK_MIN_WIDTH}px`)

    fireEvent.pointerDown(splitter, { pointerId: 8, clientX: 500 })
    fireEvent.pointerMove(splitter, { pointerId: 8, clientX: 300 })
    frames.shift()?.(0)
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('598px')
    fireEvent.pointerCancel(splitter, { pointerId: 8 })
    expect(root.style.getPropertyValue('--right-dock-width')).toBe(`${RIGHT_DOCK_MIN_WIDTH}px`)
  })

  it('reclamps on viewport resize and reset clears persistence', () => {
    localStorage.setItem(RIGHT_DOCK_STORAGE_KEY, '700')
    const { container } = render(<Harness />)
    const root = container.querySelector('main')!
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('700px')
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1100 })
    fireEvent(window, new Event('resize'))
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('454px')

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(root.style.getPropertyValue('--right-dock-width')).toBe('418px')
    expect(localStorage.getItem(RIGHT_DOCK_STORAGE_KEY)).toBeNull()
  })
})
