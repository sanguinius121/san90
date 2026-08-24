// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AiReviewSaveStatus, AiReviewStatus } from '../../types/aiReview'
import { AiImagePreview } from './AiImagePreview'

const status = (overrides: Partial<AiReviewStatus> = {}): AiReviewStatus => ({
  available: true,
  reason: null,
  sequence: 10,
  timestamp_ns: 1000,
  width: 640,
  height: 640,
  center_frequency_hz: 2.45e9,
  frequency_start_hz: 2.39921875e9,
  frequency_stop_hz: 2.50078125e9,
  content_type: 'image/jpeg',
  detection_count: 2,
  received_at_ns: 1000,
  power_min_dbm: -120,
  power_max_dbm: -20,
  power_range_db: 100,
  db_per_gray_level: 100 / 255,
  power_range_generation: 0,
  ...overrides,
})

const saveStatus = (overrides: Partial<AiReviewSaveStatus> = {}): AiReviewSaveStatus => ({
  active: false,
  saved_count: 0,
  last_saved_path: null,
  last_error: null,
  ...overrides,
})

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
}))

const image = (sequence: number) => Promise.resolve(new Response(new Blob([String(sequence)], { type: 'image/jpeg' }), {
  status: 200,
  headers: { 'Content-Type': 'image/jpeg', 'X-AI-Review-Sequence': String(sequence) },
}))

const corsImage = (sequence: number) => Promise.resolve(new Response(new Blob([String(sequence)], { type: 'image/jpeg' }), {
  status: 200,
  // Browsers hide non-exposed response headers on the cross-origin
  // frontend:5173 -> backend:8000 request. The sequence-safe URL remains the
  // authoritative race check in this case.
  headers: { 'Content-Type': 'image/jpeg' },
}))

// '/api/analyzer/ai/review/save/status' contains '/status' too, so routing
// must check the more specific save paths before the generic review status.
function route(
  url: string,
  init: RequestInit | undefined,
  handlers: {
    reviewStatus?: () => Promise<Response>
    image?: () => Promise<Response>
    saveStatus?: () => Promise<Response>
    saveStart?: () => Promise<Response>
    saveStop?: () => Promise<Response>
  },
): Promise<Response> {
  if (url.includes('/save/status') && handlers.saveStatus) return handlers.saveStatus()
  if (url.includes('/save/start') && init?.method === 'POST' && handlers.saveStart) return handlers.saveStart()
  if (url.includes('/save/stop') && init?.method === 'POST' && handlers.saveStop) return handlers.saveStop()
  if (url.includes('/power-range')) return json({
    mode: 'preset', preset: 'external_lna', power_min_dbm: -120, power_max_dbm: -20,
    range_db: 100, db_per_gray_level: 100 / 255, generation: 0,
    supported_min_dbm: -140, supported_max_dbm: 10, minimum_range_db: 10,
  })
  if (url.includes('/image') && handlers.image) return handlers.image()
  if (url.includes('/status') && handlers.reviewStatus) return handlers.reviewStatus()
  throw new Error(`unexpected fetch ${url} ${init?.method ?? 'GET'}`)
}

beforeEach(() => {
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn((blob: Blob) => `blob:review-${blob.size}-${Math.random()}`),
    revokeObjectURL: vi.fn(),
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('AiImagePreview', () => {
  it('renders a waiting state with the Save toggle enabled', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(status({ available: false, reason: 'waiting', sequence: null, detection_count: 0 })),
        saveStatus: () => json(saveStatus()),
      }),
    ))
    render(<AiImagePreview />)
    expect(await screen.findByText('Waiting for AI detection')).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
    const button = screen.getByRole('button', { name: 'Lưu kết quả' }) as HTMLButtonElement
    expect(button.disabled).toBe(false)
  })

  it('fetches an annotated image only when sequence changes', async () => {
    let current = status()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(current),
        image: () => image(current.sequence!),
        saveStatus: () => json(saveStatus()),
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<AiImagePreview />)
    expect(await screen.findByRole('img', { name: 'Latest AI detection' })).toBeTruthy()
    expect(screen.getByText('Center 2450.000 MHz')).toBeTruthy()
    expect(screen.getByText('Frame 10')).toBeTruthy()
    expect(screen.getByText('2 detections')).toBeTruthy()
    const imageUrl = () => String(fetchMock.mock.calls.find(([input]) => String(input).includes('/image'))?.[0])
    expect(imageUrl()).toContain('variant=annotated')
    const imageCalls = () => fetchMock.mock.calls.filter(([input]) => String(input).includes('/image')).length
    expect(imageCalls()).toBe(1)

    window.dispatchEvent(new Event('resize'))
    await new Promise(resolve => window.setTimeout(resolve, 300))
    expect(imageCalls()).toBe(1)

    current = status({ sequence: 11, detection_count: 1 })
    await waitFor(() => expect(screen.getByText('Frame 11')).toBeTruthy(), { timeout: 1000 })
    expect(imageCalls()).toBe(2)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(screen.getByText('1 detection')).toBeTruthy()
  })

  it('revokes the final Blob URL on unmount and isolates API errors', async () => {
    let fail = false
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) => {
      if (fail) return Promise.reject(new Error('offline'))
      return route(String(input), init, {
        reviewStatus: () => json(status()),
        image: () => image(10),
        saveStatus: () => json(saveStatus()),
      })
    }))
    const view = render(<AiImagePreview />)
    expect(await screen.findByRole('img')).toBeTruthy()
    fail = true
    await waitFor(() => expect(screen.getByText('Review unavailable')).toBeTruthy(), { timeout: 1000 })
    view.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })

  it('accepts a sequence-safe image when CORS does not expose the diagnostic header', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(status()),
        image: () => corsImage(10),
        saveStatus: () => json(saveStatus()),
      }),
    ))
    render(<AiImagePreview />)
    expect(await screen.findByRole('img', { name: 'Latest AI detection' })).toBeTruthy()
    expect(screen.getByText('Frame 10')).toBeTruthy()
  })

  it('starts and stops continuous save via the toggle button', async () => {
    let active = false
    let savedCount = 0
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(status()),
        image: () => image(10),
        saveStatus: () => json(saveStatus({ active, saved_count: savedCount })),
        saveStart: () => {
          active = true
          savedCount = 3
          return json(saveStatus({ active, saved_count: savedCount }))
        },
        saveStop: () => {
          active = false
          return json(saveStatus({ active, saved_count: savedCount }))
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(<AiImagePreview />)
    const button = await screen.findByRole('button', { name: 'Lưu kết quả' })

    fireEvent.click(button)
    await screen.findByRole('button', { name: 'Dừng lưu (3)' })
    expect(screen.getByRole('button', { name: 'Dừng lưu (3)' }).getAttribute('aria-pressed')).toBe('true')
    expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).includes('/save/start') && init?.method === 'POST',
    )).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Dừng lưu (3)' }))
    await screen.findByRole('button', { name: 'Lưu kết quả' })
    expect(fetchMock.mock.calls.some(([input, init]) =>
      String(input).includes('/save/stop') && init?.method === 'POST',
    )).toBe(true)
  })

  it('reflects saved_count growing from background polling while active', async () => {
    let savedCount = 0
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(status()),
        image: () => image(10),
        saveStatus: () => json(saveStatus({ active: true, saved_count: savedCount })),
      }),
    ))
    render(<AiImagePreview />)
    await screen.findByRole('button', { name: 'Dừng lưu (0)' })
    savedCount = 5
    await waitFor(() => expect(screen.getByRole('button', { name: 'Dừng lưu (5)' })).toBeTruthy(), { timeout: 1500 })
  })

  it('shows an error message when starting continuous save fails', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request, init?: RequestInit) =>
      route(String(input), init, {
        reviewStatus: () => json(status()),
        image: () => image(10),
        saveStatus: () => json(saveStatus()),
        saveStart: () => Promise.resolve(new Response(JSON.stringify({ detail: 'disk full' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        })),
      }),
    ))
    render(<AiImagePreview />)
    const button = await screen.findByRole('button', { name: 'Lưu kết quả' })
    fireEvent.click(button)
    expect(await screen.findByText('Start save failed (500)')).toBeTruthy()
  })
})
