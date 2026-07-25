import type { AiDetectionResult } from '../types'

export type AiDetectionListener = (result: AiDetectionResult) => void

class AiDetectionBus {
  private listeners = new Set<AiDetectionListener>()
  private latest: AiDetectionResult | null = null

  publish(result: AiDetectionResult) {
    this.latest = result
    this.listeners.forEach((listener) => listener(result))
  }

  subscribe(listener: AiDetectionListener) {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  getLatest() {
    return this.latest
  }

  clear() {
    this.latest = null
  }
}

export const aiDetections = new AiDetectionBus()
