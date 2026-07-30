import type {
  RecordingConfig,
  RecordingConfigUpdate,
  RecordingDirectoryList,
  RecordingStatus,
} from '../types/recording'

const base = `http://${location.hostname}:8000`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  const body: unknown = await response.json().catch(() => ({}))
  if (!response.ok) {
    const payload = body as {
      error?: { message?: string }
      detail?: string | { message?: string }
    }
    const detail = payload.detail
    const message =
      payload.error?.message ??
      (typeof detail === 'string' ? detail : detail?.message) ??
      `Recording request failed (${response.status})`
    throw new Error(message)
  }
  return body as T
}

export const recordingApi = {
  config: () => request<RecordingConfig>('/api/analyzer/recording/config'),
  updateConfig: (config: RecordingConfigUpdate) =>
    request<RecordingConfig>('/api/analyzer/recording/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  directories: () =>
    request<RecordingDirectoryList>('/api/analyzer/recording/directories'),
  createDirectory: (path: string) =>
    request<RecordingDirectoryList>('/api/analyzer/recording/directories', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  start: () =>
    request<RecordingStatus>('/api/analyzer/recording/start', {
      method: 'POST',
    }),
  stop: () =>
    request<RecordingStatus>('/api/analyzer/recording/stop', {
      method: 'POST',
    }),
  status: () => request<RecordingStatus>('/api/analyzer/recording/status'),
}
