import type { AiPreviewStatus } from '../types/aiPreview'

const base = () => `http://${location.hostname}:8000`

export const aiPreviewApi = {
  async status(signal?: AbortSignal, viewer = true): Promise<AiPreviewStatus> {
    const response = await fetch(`${base()}/api/analyzer/ai/preview/status?viewer=${viewer}`, {
      cache: 'no-store',
      signal,
    })
    if (!response.ok) throw new Error(`Preview status failed (${response.status})`)
    return response.json() as Promise<AiPreviewStatus>
  },

  async image(sequence: number, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(
      `${base()}/api/analyzer/ai/preview/image?sequence=${encodeURIComponent(sequence)}`,
      { cache: 'no-store', signal },
    )
    if (!response.ok) throw new Error(`Preview image failed (${response.status})`)
    const sequenceHeader = response.headers.get('X-AI-Preview-Sequence')
    const returned = sequenceHeader === null ? null : Number(sequenceHeader)
    if (returned !== null && Number.isFinite(returned) && returned !== sequence) {
      throw new Error('Preview image sequence changed during retrieval')
    }
    return response.blob()
  },
}
