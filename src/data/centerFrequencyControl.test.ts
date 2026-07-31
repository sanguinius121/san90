// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { liveFrames } from './liveFrames'
import {
  commitCenterFrequencyHz,
  validateCenterFrequencyHz,
} from './centerFrequencyControl'
import { useDeviceStore, useRuntimeStore } from '../stores'

describe('shared center-frequency commit', () => {
  beforeEach(() => {
    useDeviceStore.setState({ centerHz: 2.45e9, spanHz: 100e6 })
    useRuntimeStore.setState({
      source: 'simulator',
      connection: 'mock',
      configurationGeneration: 3,
      reconfiguring: false,
      playbackActive: false,
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
      lastError: undefined,
    })
    liveFrames.clear()
  })

  it('validates the canonical Hz value', () => {
    const limits = { minimumHz: 100, maximumHz: 1000 }
    expect(validateCenterFrequencyHz(100, limits)).toBe(true)
    expect(validateCenterFrequencyHz(1000, limits)).toBe(true)
    expect(validateCenterFrequencyHz(0, limits)).toBe(false)
    expect(validateCenterFrequencyHz(Number.NaN, limits)).toBe(false)
    expect(validateCenterFrequencyHz(Number.POSITIVE_INFINITY, limits)).toBe(false)
  })

  it('performs one simulator configuration commit and advances generation', async () => {
    const result = await commitCenterFrequencyHz(2_460_000_000)
    expect(result).toEqual({
      actualCenterHz: 2_460_000_000,
      configurationGeneration: 4,
    })
    expect(useDeviceStore.getState().centerHz).toBe(2_460_000_000)
    expect(useRuntimeStore.getState().configurationGeneration).toBe(4)
    expect(useRuntimeStore.getState().reconfiguring).toBe(false)
  })

  it('rounds the final request to integer Hz', async () => {
    const result = await commitCenterFrequencyHz(2_460_000_000.49)
    expect(result && result.actualCenterHz).toBe(2_460_000_000)
  })

  it('blocks commits during playback and Frequency Scan', async () => {
    useRuntimeStore.setState({ playbackActive: true })
    expect(await commitCenterFrequencyHz(2.46e9)).toBe(false)
    expect(useDeviceStore.getState().centerHz).toBe(2.45e9)
    useRuntimeStore.setState({
      playbackActive: false,
      frequencyScan: {
        ...useRuntimeStore.getState().frequencyScan,
        running: true,
        state: 'dwelling',
      },
    })
    expect(await commitCenterFrequencyHz(2.46e9)).toBe(false)
    expect(useDeviceStore.getState().centerHz).toBe(2.45e9)
  })

  it('does not invoke a hardware request for invalid values', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    expect(await commitCenterFrequencyHz(-1)).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
    fetchMock.mockRestore()
  })
})
