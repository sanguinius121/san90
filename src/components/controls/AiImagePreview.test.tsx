// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AiPreviewStatus } from '../../types/aiPreview'
import { AiImagePreview } from './AiImagePreview'

const status = (overrides: Partial<AiPreviewStatus> = {}): AiPreviewStatus => ({
  available: true,
  reason: null,
  sequence: 10,
  source: 'hardware',
  playback_epoch: null,
  config_id: null,
  configuration_generation: 2,
  center_frequency_hz: 2.45e9,
  frequency_start_hz: 2.39921875e9,
  frequency_stop_hz: 2.50078125e9,
  width: 640,
  height: 640,
  created_at_ns: 1000,
  content_type: 'image/png',
  ...overrides,
})

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
}))

const image = (sequence: number) => Promise.resolve(new Response(new Blob([String(sequence)], { type: 'image/png' }), {
  status: 200,
  headers: { 'Content-Type': 'image/png', 'X-AI-Preview-Sequence': String(sequence) },
}))

const corsImage = (sequence: number) => Promise.resolve(new Response(new Blob([String(sequence)], { type: 'image/png' }), {
  status: 200,
  // Browsers hide non-exposed response headers on the cross-origin
  // frontend:5173 -> backend:8000 request. The sequence-safe URL remains the
  // authoritative race check in this case.
  headers: { 'Content-Type': 'image/png' },
}))

beforeEach(() => {
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn((blob: Blob) => `blob:preview-${blob.size}-${Math.random()}`),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AiImagePreview', () => {
  it('renders compact waiting and playback-disabled states', async () => {
    vi.stubGlobal('fetch', vi.fn(() => json(status({
      available: false,
      reason: 'playback_ai_disabled',
      sequence: null,
      source: 'playback',
    }))))
    render(<AiImagePreview />)
    expect(await screen.findByText('AI preview disabled for playback')).toBeTruthy()
    expect(screen.getByText('PLAYBACK')).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('fetches an image only when sequence changes and keeps resize CSS-only', async () => {
    let current = status()
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      return url.includes('/status') ? json(current) : image(current.sequence!)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AiImagePreview />)
    expect(await screen.findByRole('img', { name: 'Latest AI input' })).toBeTruthy()
    expect(String(fetchMock.mock.calls[0][0])).toContain('viewer=true')
    expect(screen.getByText('HARDWARE')).toBeTruthy()
    expect(screen.getByText('Center 2450.000 MHz')).toBeTruthy()
    expect(screen.getByText('Frame 10')).toBeTruthy()
    const imageCalls = () => fetchMock.mock.calls.filter(([input]) => String(input).includes('/image')).length
    expect(imageCalls()).toBe(1)

    window.dispatchEvent(new Event('resize'))
    await new Promise(resolve => window.setTimeout(resolve, 300))
    expect(imageCalls()).toBe(1)

    current = status({ sequence: 11, source: 'simulator' })
    await waitFor(() => expect(screen.getByText('Frame 11')).toBeTruthy(), { timeout: 1000 })
    expect(imageCalls()).toBe(2)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(screen.getByText('SIMULATOR')).toBeTruthy()
  })

  it('revokes the final Blob URL on unmount and isolates API errors', async () => {
    let fail = false
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      if (fail) return Promise.reject(new Error('offline'))
      return String(input).includes('/status') ? json(status({ source: 'playback', playback_epoch: 4 })) : image(10)
    }))
    const view = render(<AiImagePreview />)
    expect(await screen.findByRole('img')).toBeTruthy()
    expect(screen.getByText('PLAYBACK')).toBeTruthy()
    fail = true
    await waitFor(() => expect(screen.getByText('Preview unavailable')).toBeTruthy(), { timeout: 1000 })
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })

  it('accepts a sequence-safe image when CORS does not expose the diagnostic header', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) =>
      String(input).includes('/status') ? json(status()) : corsImage(10),
    ))
    render(<AiImagePreview />)
    expect(await screen.findByRole('img', { name: 'Latest AI input' })).toBeTruthy()
    expect(screen.getByText('Frame 10')).toBeTruthy()
  })

  it('does not renew the encoder lease while the page is hidden', async () => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    const fetchMock = vi.fn((input: string | URL | Request) =>
      String(input).includes('/status')
        ? json(status({ available: false, sequence: null }))
        : corsImage(10),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<AiImagePreview />)
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(String(fetchMock.mock.calls[0][0])).toContain('viewer=false')
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  })
})
