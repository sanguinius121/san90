import type { PlaybackStatus, RecordingSummary } from '../types/playback'

const base = `http://${location.hostname}:8000`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body: unknown = await response.json().catch(() => ({}))
  if (!response.ok) {
    const payload = body as { detail?: string | { message?: string }; error?: { message?: string } }
    const detail = payload.detail
    throw new Error(
      payload.error?.message ??
        (typeof detail === 'string' ? detail : detail?.message) ??
        `Playback request failed (${response.status})`,
    )
  }
  return body as T
}

const post = (path: string, body?: object) =>
  request<PlaybackStatus>(path, {
    method: 'POST',
    ...(body ? { body: JSON.stringify(body) } : {}),
  })

export const playbackApi = {
  recordings: async () =>
    (await request<{ recordings: RecordingSummary[] }>('/api/analyzer/recordings')).recordings,
  status: () => request<PlaybackStatus>('/api/analyzer/playback/status'),
  open: (recordingId: string) =>
    post('/api/analyzer/playback/open', { recording_id: recordingId }),
  play: () => post('/api/analyzer/playback/play'),
  pause: () => post('/api/analyzer/playback/pause'),
  stop: () => post('/api/analyzer/playback/stop'),
  seek: (positionS: number) => post('/api/analyzer/playback/seek', { position_s: positionS }),
  step: (direction: 'previous' | 'next') =>
    post('/api/analyzer/playback/step', { direction }),
  settings: (autoLoop: boolean, runAi: boolean) =>
    request<PlaybackStatus>('/api/analyzer/playback/settings', {
      method: 'PUT',
      body: JSON.stringify({ auto_loop: autoLoop, run_ai: runAi }),
    }),
}
