import type { AiReviewSaveStatus, AiReviewStatus } from '../types/aiReview'

const base = () => `http://${location.hostname}:8000`

export const aiReviewApi = {
  async status(signal?: AbortSignal): Promise<AiReviewStatus> {
    const response = await fetch(`${base()}/api/analyzer/ai/review/status`, {
      cache: 'no-store',
      signal,
    })
    if (!response.ok) throw new Error(`Review status failed (${response.status})`)
    return response.json() as Promise<AiReviewStatus>
  },

  async image(sequence: number, signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(
      `${base()}/api/analyzer/ai/review/image?sequence=${encodeURIComponent(sequence)}&variant=annotated`,
      { cache: 'no-store', signal },
    )
    if (!response.ok) throw new Error(`Review image failed (${response.status})`)
    const sequenceHeader = response.headers.get('X-AI-Review-Sequence')
    const returned = sequenceHeader === null ? null : Number(sequenceHeader)
    if (returned !== null && Number.isFinite(returned) && returned !== sequence) {
      throw new Error('Review image sequence changed during retrieval')
    }
    return response.blob()
  },

  async saveStatus(signal?: AbortSignal): Promise<AiReviewSaveStatus> {
    const response = await fetch(`${base()}/api/analyzer/ai/review/save/status`, {
      cache: 'no-store',
      signal,
    })
    if (!response.ok) throw new Error(`Save status failed (${response.status})`)
    return response.json() as Promise<AiReviewSaveStatus>
  },

  async startSave(signal?: AbortSignal): Promise<AiReviewSaveStatus> {
    const response = await fetch(`${base()}/api/analyzer/ai/review/save/start`, { method: 'POST', signal })
    if (!response.ok) throw new Error(`Start save failed (${response.status})`)
    return response.json() as Promise<AiReviewSaveStatus>
  },

  async stopSave(signal?: AbortSignal): Promise<AiReviewSaveStatus> {
    const response = await fetch(`${base()}/api/analyzer/ai/review/save/stop`, { method: 'POST', signal })
    if (!response.ok) throw new Error(`Stop save failed (${response.status})`)
    return response.json() as Promise<AiReviewSaveStatus>
  },
}
