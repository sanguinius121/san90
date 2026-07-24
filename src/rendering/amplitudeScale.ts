import type { Viewport } from "../types";

export const DEFAULT_SPECTRUM_DYNAMIC_RANGE_DB = 100;

export function spectrumRangeForReferenceLevel(
  referenceLevelDbm: number,
  dynamicRangeDb = DEFAULT_SPECTRUM_DYNAMIC_RANGE_DB,
): Pick<Viewport, "minDbm" | "maxDbm"> {
  if (!Number.isFinite(referenceLevelDbm) || !Number.isFinite(dynamicRangeDb) || dynamicRangeDb <= 0)
    throw new Error("Spectrum amplitude range must be finite and positive");
  return {
    minDbm: referenceLevelDbm - dynamicRangeDb,
    maxDbm: referenceLevelDbm,
  };
}

export function spectrumAmplitudeFraction(
  amplitudeDbm: number,
  range: Pick<Viewport, "minDbm" | "maxDbm">,
): number {
  return (amplitudeDbm - range.minDbm) / (range.maxDbm - range.minDbm);
}

export function spectrumAmplitudeTicks(
  range: Pick<Viewport, "minDbm" | "maxDbm">,
  divisions = 10,
): number[] {
  return Array.from(
    { length: divisions + 1 },
    (_, index) => range.maxDbm - ((range.maxDbm - range.minDbm) * index) / divisions,
  );
}
