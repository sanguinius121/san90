// @vitest-environment jsdom

import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { liveFrames } from '../data/liveFrames'
import { useDeviceStore, useDisplayStore, useRuntimeStore } from '../stores'
import type { SpectrumFrame } from '../types'
import { SpectrumPanel } from './SpectrumPanel'

const mocks = vi.hoisted(() => ({
  commit: vi.fn(),
  offsets: [] as Array<[number, number]>,
  dimmed: [] as boolean[],
}))

vi.mock('../data/centerFrequencyControl', async (importOriginal) => {
  const actual = await importOriginal<
    typeof import('../data/centerFrequencyControl')
  >()
  return { ...actual, commitCenterFrequencyHz: mocks.commit }
})

vi.mock('../rendering/SpectrumRenderer', async (importOriginal) => {
  const actual = await importOriginal<
    typeof import('../rendering/SpectrumRenderer')
  >()
  return {
    ...actual,
    SpectrumRenderer: class {
      setFrame() {}
      setPanOffsetPixels(offset: number, width: number) {
        mocks.offsets.push([offset, width])
      }
      setPanDimmed(dimmed: boolean) {
        mocks.dimmed.push(dimmed)
      }
      render() {}
      dispose() {}
    },
  }
})

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

const frame = (
  centerHz = 2.45e9,
  generation = 1,
): SpectrumFrame => ({
  sequence: generation,
  timestamp: Date.now(),
  source: 'simulator',
  configurationGeneration: generation,
  startHz: centerHz - 50e6,
  centerHz,
  stopHz: centerHz + 50e6,
  spanHz: 100e6,
  values: new Float32Array([1, 2, 3, 4]),
  intervalMaxValues: new Float32Array([1, 2, 3, 4]),
  waterfall: new Uint8Array(),
})

describe('Spectrum Pan pointer lifecycle', () => {
  let rafCallbacks: FrameRequestCallback[]

  beforeEach(() => {
    rafCallbacks = []
    mocks.commit.mockReset()
    mocks.offsets.length = 0
    mocks.dimmed.length = 0
    vi.stubGlobal('ResizeObserver', ResizeObserverStub)
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((callback: FrameRequestCallback) => {
        rafCallbacks.push(callback)
        return rafCallbacks.length
      }),
    )
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 1000,
        bottom: 300,
        width: 1000,
        height: 300,
        toJSON: () => ({}),
      }),
    })
    HTMLElement.prototype.setPointerCapture = vi.fn()
    HTMLElement.prototype.releasePointerCapture = vi.fn()
    HTMLElement.prototype.hasPointerCapture = vi.fn(() => true)
    useDeviceStore.setState({ centerHz: 2.45e9, spanHz: 100e6 })
    useDisplayStore.setState({
      activeTool: 'pan',
      panPhase: 'armed',
      marker: null,
      viewport: { start: 0, end: 1, minDbm: -120, maxDbm: 0 },
    })
    useRuntimeStore.setState({
      source: 'simulator',
      connection: 'mock',
      reconfiguring: false,
      playbackActive: false,
      configurationGeneration: 1,
      frequencyScan: {
        running: false,
        state: 'idle',
        active_entry_id: null,
        active_index: null,
        active_count: 0,
        verified_center_frequency_hz: null,
        dwell_duration_seconds: null,
        remaining_dwell_seconds: null,
        last_error: null,
      },
    })
    liveFrames.clear()
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  const setup = () => {
    const view = render(<SpectrumPanel />)
    act(() => liveFrames.publish(frame()))
    return view.container.querySelector('.plot-stage') as HTMLElement
  }

  it('starts only inside the shared plot rectangle', () => {
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 20, clientY: 100 })
    expect(useDisplayStore.getState().panPhase).toBe('armed')
    fireEvent.pointerDown(stage, { pointerId: 2, clientX: 500, clientY: 100 })
    expect(useDisplayStore.getState().panPhase).toBe('dragging')
  })

  it('RAF-throttles visual movement and sends no request before release', () => {
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    const scheduledBeforeMove = rafCallbacks.length
    fireEvent.pointerMove(stage, { pointerId: 1, clientX: 450, clientY: 100 })
    fireEvent.pointerMove(stage, { pointerId: 1, clientX: 440, clientY: 100 })
    expect(rafCallbacks.length).toBe(scheduledBeforeMove + 1)
    expect(mocks.commit).not.toHaveBeenCalled()
    act(() => rafCallbacks.at(-1)?.(performance.now()))
    expect(mocks.offsets.at(-1)?.[0]).toBeCloseTo(-60)
  })

  it('does not tune below the four-pixel threshold', () => {
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    fireEvent.pointerUp(stage, { pointerId: 1, clientX: 503, clientY: 100 })
    expect(mocks.commit).not.toHaveBeenCalled()
    expect(useDisplayStore.getState().panPhase).toBe('armed')
    expect(mocks.offsets.at(-1)).toEqual([0, 1])
  })

  it('commits exactly once and waits for the verified new packet', async () => {
    const stage = setup()
    const expectedCenter = 2.45e9 + 100e6 * (60 / 942)
    mocks.commit.mockResolvedValue({
      actualCenterHz: Math.round(expectedCenter),
      configurationGeneration: 2,
    })
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    await act(async () => {
      fireEvent.pointerMove(stage, {
        pointerId: 1,
        clientX: 440,
        clientY: 100,
      })
      fireEvent.pointerUp(stage, {
        pointerId: 1,
        clientX: 440,
        clientY: 100,
      })
      await Promise.resolve()
    })
    expect(mocks.commit).toHaveBeenCalledTimes(1)
    expect(mocks.commit.mock.calls[0][0]).toBeCloseTo(expectedCenter)
    expect(useDisplayStore.getState().panPhase).toBe('tuning')
    act(() => liveFrames.publish(frame(2.45e9, 1)))
    expect(useDisplayStore.getState().panPhase).toBe('tuning')
    act(() => liveFrames.publish(frame(Math.round(expectedCenter), 2)))
    expect(useDisplayStore.getState().panPhase).toBe('armed')
    expect(mocks.offsets.at(-1)).toEqual([0, 1])
  })

  it('restores the verified view when the shared commit fails', async () => {
    const stage = setup()
    mocks.commit.mockResolvedValue(false)
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    await act(async () => {
      fireEvent.pointerUp(stage, {
        pointerId: 1,
        clientX: 440,
        clientY: 100,
      })
      await Promise.resolve()
    })
    expect(mocks.commit).toHaveBeenCalledTimes(1)
    expect(useDisplayStore.getState().panPhase).toBe('armed')
    expect(mocks.offsets.at(-1)).toEqual([0, 1])
    expect(mocks.dimmed.at(-1)).toBe(false)
  })

  it('cancels on pointercancel and Escape without committing', () => {
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    fireEvent.pointerMove(stage, { pointerId: 1, clientX: 450, clientY: 100 })
    fireEvent.pointerCancel(stage, { pointerId: 1 })
    expect(mocks.commit).not.toHaveBeenCalled()
    expect(useDisplayStore.getState().panPhase).toBe('armed')

    fireEvent.pointerDown(stage, { pointerId: 2, clientX: 500, clientY: 100 })
    fireEvent.pointerMove(stage, { pointerId: 2, clientX: 450, clientY: 100 })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(mocks.commit).not.toHaveBeenCalled()
    expect(useDisplayStore.getState().panPhase).toBe('armed')
  })

  it('scan activation cancels an active drag', () => {
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    expect(useDisplayStore.getState().panPhase).toBe('dragging')
    act(() => useRuntimeStore.setState({
      frequencyScan: {
        ...useRuntimeStore.getState().frequencyScan,
        running: true,
        state: 'dwelling',
      },
    }))
    expect(useDisplayStore.getState().panPhase).toBe('off')
    expect(mocks.commit).not.toHaveBeenCalled()
  })

  it('does not arm or drag while playback owns the display', () => {
    useRuntimeStore.setState({
      source: 'playback',
      playbackActive: true,
      playbackState: 'paused',
    })
    const stage = setup()
    fireEvent.pointerDown(stage, { pointerId: 1, clientX: 500, clientY: 100 })
    expect(useDisplayStore.getState().panPhase).toBe('off')
    expect(mocks.commit).not.toHaveBeenCalled()
  })
})
