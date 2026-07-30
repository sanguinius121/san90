// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useRuntimeStore } from '../../stores'
import type { PlaybackStatus } from '../../types/playback'
import { PlaybackControl } from './PlaybackControl'

const idle: PlaybackStatus = {
  state: 'idle', recording_id: null, filename: null, position_s: 0, duration_s: 0,
  progress: 0, current_sequence: null, current_record_index: null, current_trace_index: null,
  current_config_id: null, configuration_generation: null, center_frequency_hz: null,
  point_count: null, gaps_passed: 0, reconfiguration_pauses_passed: 0,
  lost_traces_passed: 0, auto_loop: false, loop_count: 0, run_ai: false,
  playback_epoch: 0, ai_warning: null, source: 'playback', previous_source: null,
  last_error: null,
}

const ready: PlaybackStatus = {
  ...idle, state: 'ready', recording_id: 'safe-id', filename: 'clean.san90rta',
  duration_s: 10, current_config_id: 2, configuration_generation: 4,
  center_frequency_hz: 2_450_000_000, point_count: 3328, previous_source: 'hardware',
  playback_epoch: 1,
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json' },
  }))
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  useRuntimeStore.setState({ playbackActive: false, playbackState: 'idle' })
})

describe('PlaybackControl', () => {
  it('lists clean files, opens explicitly, and contains no speed control', async () => {
    let current = idle
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      calls.push(url)
      if (url.endsWith('/recordings')) return response({ recordings: [{
        id: 'safe-id', filename: 'clean.san90rta', size_bytes: 1024, created_at: null,
        duration_s: 10, trace_count: 5, batch_count: 2, config_count: 1, gap_count: 0,
        lost_trace_count: 0, stop_reason: 'fixed_duration', complete: true, clean: true,
        playable: true, error: null,
      }] })
      if (url.endsWith('/playback/status')) return response(current)
      if (url.endsWith('/playback/open')) {
        current = ready
        return response(current)
      }
      return response({}, 404)
    }))
    render(<PlaybackControl />)
    expect(await screen.findByText(/clean\.san90rta/)).toBeTruthy()
    expect(screen.queryByText(/speed/i)).toBeNull()
    fireEvent.click(screen.getByLabelText('Open recording'))
    await waitFor(() => expect(useRuntimeStore.getState().playbackActive).toBe(true))
    expect(calls.some(url => url.endsWith('/playback/open'))).toBe(true)
    expect(screen.getByText('2.45 GHz · 3,328 points')).toBeTruthy()
  })

  it('calls play, pause, relative seek, step, stop, and settings APIs', async () => {
    let current = ready
    const requests: Array<{ url: string; body: Record<string, unknown> | null }> = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/recordings')) return response({ recordings: [] })
      if (url.endsWith('/playback/status')) return response(current)
      const body = init?.body ? JSON.parse(String(init.body)) : null
      requests.push({ url, body })
      if (url.endsWith('/play')) current = { ...current, state: 'playing' }
      if (url.endsWith('/pause')) current = { ...current, state: 'paused' }
      if (url.endsWith('/seek')) current = { ...current, state: 'paused', position_s: Number(body.position_s) }
      if (url.endsWith('/step')) current = { ...current, state: 'paused', current_trace_index: 1 }
      if (url.endsWith('/settings')) current = { ...current, auto_loop: Boolean(body.auto_loop), run_ai: Boolean(body.run_ai) }
      if (url.endsWith('/stop')) current = idle
      return response(current)
    }))
    render(<PlaybackControl />)
    await screen.findByLabelText('Play playback')
    fireEvent.click(screen.getByLabelText('Play playback'))
    await screen.findByLabelText('Pause playback')
    fireEvent.click(screen.getByLabelText('Pause playback'))
    await screen.findByLabelText('Play playback')
    fireEvent.click(screen.getByLabelText('Forward 5 seconds'))
    await waitFor(() => expect(requests.some(item => item.url.endsWith('/seek') && item.body?.position_s === 5)).toBe(true))
    fireEvent.click(screen.getByLabelText('Next trace'))
    await waitFor(() => expect(requests.some(item => item.url.endsWith('/step') && item.body?.direction === 'next')).toBe(true))
    fireEvent.click(screen.getByLabelText('Toggle Auto Loop'))
    await waitFor(() => expect(requests.some(item => item.url.endsWith('/settings') && item.body?.auto_loop === true)).toBe(true))
    fireEvent.click(screen.getByLabelText('Stop playback'))
    await waitFor(() => expect(requests.some(item => item.url.endsWith('/stop'))).toBe(true))
  })

  it('protects timeline draft from polling and seeks once on release', async () => {
    let current = { ...ready, state: 'paused' as const, position_s: 2 }
    const seeks: number[] = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/recordings')) return response({ recordings: [] })
      if (url.endsWith('/playback/status')) return response(current)
      if (url.endsWith('/seek')) {
        const position = Number(JSON.parse(String(init?.body)).position_s)
        seeks.push(position)
        current = { ...current, position_s: position }
        return response(current)
      }
      return response(current)
    }))
    render(<PlaybackControl />)
    const slider = await screen.findByLabelText('Playback timeline') as HTMLInputElement
    await waitFor(() => expect(slider.value).toBe('2'))
    fireEvent.pointerDown(slider)
    fireEvent.change(slider, { target: { value: '6.5' } })
    current = { ...current, position_s: 3 }
    expect(slider.value).toBe('6.5')
    expect(seeks).toEqual([])
    fireEvent.pointerUp(slider)
    await waitFor(() => expect(seeks).toEqual([6.5]))
  })
})
