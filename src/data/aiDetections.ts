import type { AiDetectionResult } from '../types'

export type AiDetectionListener = (result: AiDetectionResult) => void

class AiDetectionBus {
  private listeners = new Set<AiDetectionListener>()
  private clearListeners = new Set<() => void>()
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

  subscribeClear(listener: () => void) {
    this.clearListeners.add(listener)
    return () => {
      this.clearListeners.delete(listener)
    }
  }

  getLatest() {
    return this.latest
  }

  clear() {
    this.latest = null
    this.clearListeners.forEach((listener) => listener())
  }
}

export const aiDetections = new AiDetectionBus()
