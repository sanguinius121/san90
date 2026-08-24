import type { AiPowerRange } from '../types/aiPowerRange'

const base = () => `http://${location.hostname}:8000`

export const aiPowerRangeApi = {
  async get(signal?: AbortSignal): Promise<AiPowerRange> {
    const response = await fetch(`${base()}/api/analyzer/ai/power-range`, {
      cache: 'no-store',
      signal,
    })
    if (!response.ok) throw new Error(`Power range status failed (${response.status})`)
    return response.json() as Promise<AiPowerRange>
  },

  async update(powerMinDbm: number, powerMaxDbm: number): Promise<AiPowerRange> {
    const response = await fetch(`${base()}/api/analyzer/ai/power-range`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ power_min_dbm: powerMinDbm, power_max_dbm: powerMaxDbm }),
    })
    if (!response.ok) throw new Error(`Power range update failed (${response.status})`)
    return response.json() as Promise<AiPowerRange>
  },
}
