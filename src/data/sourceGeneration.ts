import type { AnalyzerSourceType } from '../types'

export function generationAfterStatus(
  currentSource: AnalyzerSourceType | null,
  currentGeneration: number,
  nextSource: AnalyzerSourceType,
  nextGeneration: number,
): number {
  return currentSource !== nextSource
    ? nextGeneration
    : Math.max(currentGeneration, nextGeneration)
}
