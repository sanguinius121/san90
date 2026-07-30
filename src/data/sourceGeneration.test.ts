import { describe, expect, it } from 'vitest'
import { generationAfterStatus } from './sourceGeneration'

describe('source generation transitions', () => {
  it('keeps monotonic protection within one source', () => {
    expect(generationAfterStatus('san90', 7, 'san90', 6)).toBe(7)
    expect(generationAfterStatus('san90', 7, 'san90', 8)).toBe(8)
  })

  it('resets when playback yields back to a lower hardware generation', () => {
    expect(generationAfterStatus('playback', 12, 'san90', 2)).toBe(2)
    expect(generationAfterStatus('san90', 2, 'playback', 1)).toBe(1)
  })
})
