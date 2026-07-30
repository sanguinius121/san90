// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RecordControl } from './RecordControl'
import type { RecordingConfig, RecordingStatus } from '../../types/recording'

const baseConfig: RecordingConfig = {
  version: 1,
  mode: 'fixed',
  duration_s: 5,
  file_size_limit_bytes: 4 * 1024 ** 3,
  free_disk_reserve_bytes: 2 * 1024 ** 3,
  output_directory: '.',
  file_prefix: 'SAN90_RTA',
  recording_root: '/server/private/recordings',
  load_warning: null,
  save_error: null,
}

const idleStatus: RecordingStatus = {
  state: 'idle',
  session_uuid: null,
  part_file_path: null,
  final_file_path: null,
  mode: null,
  elapsed_s: 0,
  written_bytes: 0,
  trace_count: 0,
  batch_count: 0,
  gap_count: 0,
  lost_trace_count: 0,
  queue_bytes: 0,
  queue_items: 0,
  queue_fill_ratio: 0,
  queue_item_fill_ratio: 0,
  queue_high_water_bytes: 0,
  queue_high_water_items: 0,
  enqueued_batches: 0,
  written_batches: 0,
  rejected_batches: 0,
  rejected_traces: 0,
  rejected_samples: 0,
  write_rate_bytes_s: 0,
  last_write_latency_ms: 0,
  stop_reason: null,
  last_error: null,
  active_config_id: null,
  active_configuration_generation: null,
  source: 'san90',
  queue_pressure: 'normal',
  available_disk_bytes: 390 * 1024 ** 3,
  total_disk_bytes: 446 * 1024 ** 3,
}

function response(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function method(init?: RequestInit) {
  return init?.method ?? 'GET'
}

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('RecordControl configuration', () => {
  it('loads fixed configuration, disk capacity, and disables duration in manual mode', async () => {
    let config = baseConfig
    const updates: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/recording/config') && method(init) === 'GET') return response(config)
      if (url.endsWith('/recording/config') && method(init) === 'PUT') {
        const update = JSON.parse(String(init?.body))
        updates.push(update)
        config = { ...config, ...update }
        return response(config)
      }
      if (url.endsWith('/recording/status')) return response(idleStatus)
      return response({}, 404)
    }))

    render(<RecordControl />)
    const mode = await screen.findByLabelText('Record mode') as HTMLSelectElement
    expect(mode.value).toBe('fixed')
    expect((screen.getByLabelText('Record time') as HTMLInputElement).value).toBe('5.0')
    expect((screen.getByLabelText('File size limit') as HTMLInputElement).value).toBe('4')
    expect(screen.getByText('390 GiB available / 446 GiB total')).toBeTruthy()

    fireEvent.change(mode, { target: { value: 'manual' } })
    await waitFor(() => expect(updates).toHaveLength(1))
    expect(updates[0]).toMatchObject({ mode: 'manual', duration_s: null })
    await waitFor(() => expect((screen.getByLabelText('Record time') as HTMLInputElement).disabled).toBe(true))
  })

  it('protects drafts, rejects invalid duration, and preserves a failed backend draft', async () => {
    let rejectSave = false
    const updates: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/recording/config') && method(init) === 'GET') return response(baseConfig)
      if (url.endsWith('/recording/config') && method(init) === 'PUT') {
        updates.push(JSON.parse(String(init?.body)))
        return rejectSave
          ? response({ detail: { message: 'Duration rejected by backend' } }, 400)
          : response({ ...baseConfig, ...updates.at(-1) })
      }
      if (url.endsWith('/recording/status')) return response({ ...idleStatus, elapsed_s: 99 })
      return response({}, 404)
    }))
    render(<RecordControl />)
    const duration = await screen.findByLabelText('Record time') as HTMLInputElement

    fireEvent.focus(duration)
    fireEvent.change(duration, { target: { value: '7.25' } })
    expect(duration.value).toBe('7.25')

    fireEvent.change(duration, { target: { value: '' } })
    fireEvent.keyDown(duration, { key: 'Enter' })
    expect(await screen.findByText(/finite positive/)).toBeTruthy()
    expect(updates).toHaveLength(0)

    rejectSave = true
    fireEvent.change(duration, { target: { value: '6.5' } })
    fireEvent.keyDown(duration, { key: 'Enter' })
    expect(await screen.findByText('Duration rejected by backend')).toBeTruthy()
    expect(duration.value).toBe('6.5')
  })

  it('preserves canonical bytes across MB/GB changes and validates relative paths', async () => {
    let config = baseConfig
    const updates: Array<Record<string, unknown>> = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/recording/config') && method(init) === 'GET') return response(config)
      if (url.endsWith('/recording/config') && method(init) === 'PUT') {
        const update = JSON.parse(String(init?.body)) as Record<string, unknown>
        updates.push(update)
        config = { ...config, ...update }
        return response(config)
      }
      if (url.endsWith('/recording/status')) return response(idleStatus)
      return response({}, 404)
    }))
    render(<RecordControl />)
    const fileSize = await screen.findByLabelText('File size limit') as HTMLInputElement
    const unit = screen.getByLabelText('File size limit unit') as HTMLSelectElement

    fireEvent.change(unit, { target: { value: 'MB' } })
    await waitFor(() => expect(updates).toHaveLength(1))
    expect(updates[0].file_size_limit_bytes).toBe(4 * 1024 ** 3)
    expect(fileSize.value).toBe('4096')

    fireEvent.change(unit, { target: { value: 'GB' } })
    await waitFor(() => expect(updates).toHaveLength(2))
    expect(updates[1].file_size_limit_bytes).toBe(4 * 1024 ** 3)
    expect(fileSize.value).toBe('4')

    const directory = screen.getByLabelText('Output directory') as HTMLInputElement
    fireEvent.focus(directory)
    fireEvent.change(directory, { target: { value: '/tmp/escape' } })
    fireEvent.blur(directory)
    expect(await screen.findByText(/must be relative/)).toBeTruthy()
    expect(updates).toHaveLength(2)
    expect(directory.value).toBe('/tmp/escape')

    fireEvent.focus(directory)
    fireEvent.change(directory, { target: { value: 'field-tests/session-01' } })
    fireEvent.blur(directory)
    await waitFor(() => expect(updates).toHaveLength(3))
    expect(updates[2].output_directory).toBe('field-tests/session-01')
  })

  it('chooses and creates safe server-side output directories', async () => {
    let config = baseConfig
    let directories = ['.', 'existing']
    const updates: Array<Record<string, unknown>> = []
    const creates: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const verb = method(init)
      if (url.endsWith('/recording/config') && verb === 'GET') return response(config)
      if (url.endsWith('/recording/config') && verb === 'PUT') {
        const update = JSON.parse(String(init?.body)) as Record<string, unknown>
        updates.push(update)
        config = { ...config, ...update }
        return response(config)
      }
      if (url.endsWith('/recording/directories') && verb === 'GET') {
        return response({ root_name: 'SAN90_Recordings', directories, created: null })
      }
      if (url.endsWith('/recording/directories') && verb === 'POST') {
        const path = (JSON.parse(String(init?.body)) as { path: string }).path
        creates.push(path)
        directories = [...directories, path]
        return response({ root_name: 'SAN90_Recordings', directories, created: path })
      }
      if (url.endsWith('/recording/status')) return response(idleStatus)
      return response({}, 404)
    }))
    render(<RecordControl />)
    await screen.findByLabelText('Output directory')

    fireEvent.click(screen.getByLabelText('Choose output directory'))
    expect(await screen.findByRole('dialog', { name: 'Choose recording directory' })).toBeTruthy()
    expect(screen.getByText('SAN90_Recordings')).toBeTruthy()
    fireEvent.click(screen.getByRole('option', { name: 'existing' }))
    await waitFor(() => expect(updates.at(-1)?.output_directory).toBe('existing'))
    expect((screen.getByLabelText('Output directory') as HTMLInputElement).value).toBe('existing')

    fireEvent.click(screen.getByLabelText('Choose output directory'))
    const newDirectory = await screen.findByLabelText('New recording directory')
    fireEvent.change(newDirectory, { target: { value: '../escape' } })
    fireEvent.click(screen.getByLabelText('Create recording directory'))
    expect(await screen.findByText(/safe relative directory/)).toBeTruthy()
    expect(creates).toHaveLength(0)

    fireEvent.change(newDirectory, { target: { value: 'field-tests/session-01' } })
    fireEvent.click(screen.getByLabelText('Create recording directory'))
    await waitFor(() => expect(creates).toEqual(['field-tests/session-01']))
    await waitFor(() => expect(updates.at(-1)?.output_directory).toBe('field-tests/session-01'))
    expect((screen.getByLabelText('Output directory') as HTMLInputElement).value).toBe(
      'field-tests/session-01',
    )
    expect(screen.queryByRole('dialog', { name: 'Choose recording directory' })).toBeNull()
  })
})

describe('RecordControl lifecycle and status', () => {
  it('commits pending config before one start, locks controls, and sends one stop', async () => {
    let config = baseConfig
    let currentStatus = idleStatus
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      const verb = method(init)
      if (url.endsWith('/recording/config') && verb === 'GET') return response(config)
      if (url.endsWith('/recording/config') && verb === 'PUT') {
        calls.push('config')
        const update = JSON.parse(String(init?.body))
        config = { ...config, ...update }
        return response(config)
      }
      if (url.endsWith('/recording/status')) return response(currentStatus)
      if (url.endsWith('/recording/start')) {
        calls.push('start')
        currentStatus = {
          ...idleStatus,
          state: 'recording',
          mode: 'fixed',
          session_uuid: 'session',
          elapsed_s: 0.2,
          part_file_path: '/private/root/test.san90rta.part',
        }
        return response(currentStatus)
      }
      if (url.endsWith('/recording/stop')) {
        calls.push('stop')
        currentStatus = { ...currentStatus, state: 'stopping' }
        return response(currentStatus)
      }
      return response({}, 404)
    }))
    render(<RecordControl />)
    const duration = await screen.findByLabelText('Record time') as HTMLInputElement
    fireEvent.focus(duration)
    fireEvent.change(duration, { target: { value: '8.5' } })

    const start = screen.getByLabelText('Start recording')
    fireEvent.click(start)
    fireEvent.click(start)
    await waitFor(() => expect(calls).toEqual(['config', 'start']))
    expect((screen.getByLabelText('Record mode') as HTMLSelectElement).disabled).toBe(true)
    expect(screen.getByRole('status').textContent).toContain('RECORDING')
    expect(screen.getByText('test.san90rta.part')).toBeTruthy()
    expect(screen.queryByText('/private/root/test.san90rta.part')).toBeNull()

    const stop = screen.getByLabelText('Stop recording')
    fireEvent.click(stop)
    fireEvent.click(stop)
    await waitFor(() => expect(calls.filter(call => call === 'stop')).toHaveLength(1))
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('STOPPING'))
  })

  it('renders completion, readable stop reason, metrics, warnings, and backend error', async () => {
    const completed: RecordingStatus = {
      ...idleStatus,
      state: 'completed',
      mode: 'fixed',
      elapsed_s: 5.03,
      written_bytes: 84_788_679,
      trace_count: 25_422,
      batch_count: 1_338,
      gap_count: 2,
      lost_trace_count: 0,
      rejected_batches: 0,
      write_rate_bytes_s: 16_150_000,
      queue_fill_ratio: 0.002,
      stop_reason: 'fixed_duration',
      final_file_path: '/secret/acceptance.san90rta',
    }
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/recording/config')) return response(baseConfig)
      if (url.endsWith('/recording/status')) return response(completed)
      return response({}, 404)
    }))
    render(<RecordControl />)
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('COMPLETED'))
    expect(screen.getByText('Recording time reached')).toBeTruthy()
    expect(screen.getByText(/25,422 traces/)).toBeTruthy()
    expect(screen.getByText(/Batches 1,338 · Gaps 2 · Lost 0/)).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toContain('2 gaps')
    expect((screen.getByLabelText('Record mode') as HTMLSelectElement).disabled).toBe(false)
  })

  it('polls active state at 250 ms, idle at 750 ms, and preserves state on failure', async () => {
    vi.useFakeTimers()
    let currentStatus: RecordingStatus = { ...idleStatus, state: 'recording', mode: 'manual' }
    let fail = false
    let statusCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/recording/config')) return response(baseConfig)
      if (url.endsWith('/recording/status')) {
        statusCalls += 1
        return fail ? Promise.reject(new Error('Backend unavailable')) : response(currentStatus)
      }
      return response({}, 404)
    }))
    render(<RecordControl />)
    await act(async () => {})
    expect(statusCalls).toBe(1)

    await act(async () => {
      vi.advanceTimersByTime(250)
    })
    await act(async () => {})
    expect(statusCalls).toBe(2)

    fail = true
    await act(async () => {
      vi.advanceTimersByTime(250)
      await Promise.resolve()
    })
    expect(screen.getByText('Backend unavailable')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toContain('RECORDING')

    fail = false
    currentStatus = idleStatus
    await act(async () => {
      vi.advanceTimersByTime(750)
      await Promise.resolve()
    })
    expect(screen.getByRole('status').textContent).toContain('IDLE')
    expect(screen.queryByText('Backend unavailable')).toBeNull()

    const callsAtIdle = statusCalls
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(statusCalls).toBe(callsAtIdle)
    await act(async () => {
      vi.advanceTimersByTime(250)
    })
    await act(async () => {})
    expect(statusCalls).toBe(callsAtIdle + 1)
  })
})
