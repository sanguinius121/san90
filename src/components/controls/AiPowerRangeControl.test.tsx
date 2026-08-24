// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiPowerRangeControl } from './AiPowerRangeControl'

const range = (low = -120, high = -20, generation = 0) => ({
  mode: low === -120 && high === -20 ? 'preset' : 'custom',
  preset: low === -120 && high === -20 ? 'external_lna' : null,
  power_min_dbm: low,
  power_max_dbm: high,
  range_db: high - low,
  db_per_gray_level: (high - low) / 255,
  generation,
  supported_min_dbm: -140,
  supported_max_dbm: 10,
  minimum_range_db: 10,
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AiPowerRangeControl', () => {
  it('loads External LNA and renders both accessible handles and derived values', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(range()), { status: 200 }))))
    render(<AiPowerRangeControl previewGeneration={0} />)
    expect(await screen.findByText('100 dB')).toBeTruthy()
    expect(screen.getByText('0.392 dB/level')).toBeTruthy()
    expect((screen.getByRole('slider', { name: 'Lower power threshold' }) as HTMLInputElement).value).toBe('-120')
    expect((screen.getByRole('slider', { name: 'Upper power threshold' }) as HTMLInputElement).value).toBe('-20')
    expect(screen.getByRole('button', { name: 'Ext. LNA' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps drag as a draft and sends one PUT only on release', async () => {
    let current = range()
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        current = range(body.power_min_dbm, body.power_max_dbm, 1)
      }
      return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AiPowerRangeControl previewGeneration={0} />)
    const low = await screen.findByRole('slider', { name: 'Lower power threshold' })
    fireEvent.pointerDown(low)
    fireEvent.change(low, { target: { value: '-100' } })
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(0)
    expect(screen.getByText('80 dB')).toBeTruthy()
    fireEvent.pointerUp(low)
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1))
    expect(JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')?.[1]?.body))).toEqual({
      power_min_dbm: -100,
      power_max_dbm: -20,
    })
  })

  it('commits a preset once and identifies its active state', async () => {
    let current = range(-100, -50, 2)
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === 'PUT') current = range(-130, -50, 3)
      return Promise.resolve(new Response(JSON.stringify(current), { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AiPowerRangeControl previewGeneration={2} />)
    const normal = await screen.findByRole('button', { name: 'Normal' })
    fireEvent.click(normal)
    await waitFor(() => expect(normal.getAttribute('aria-pressed')).toBe('true'))
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
  })

  it('shows applying until preview generation matches committed generation', async () => {
    let next = range(-100, -50, 3)
    vi.stubGlobal('fetch', vi.fn((_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === 'PUT') next = range(-130, -50, 4)
      return Promise.resolve(new Response(JSON.stringify(next), { status: 200 }))
    }))
    const view = render(<AiPowerRangeControl previewGeneration={3} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Normal' }))
    expect(await screen.findByText('APPLYING…')).toBeTruthy()
    view.rerender(<AiPowerRangeControl previewGeneration={4} />)
    await waitFor(() => expect(screen.queryByText('APPLYING…')).toBeNull())
  })
})
