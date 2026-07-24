import { beforeEach, describe, expect, it } from "vitest";
import { useDisplayStore } from "../stores";
import {
  spectrumAmplitudeFraction,
  spectrumAmplitudeTicks,
} from "./amplitudeScale";

beforeEach(() => {
  useDisplayStore.setState({
    viewport: { start: 0, end: 1, minDbm: -110, maxDbm: -10 },
  });
});

describe("verified reference-level spectrum scaling", () => {
  it("places a verified 0 dBm reference at the top while retaining 100 dB", () => {
    useDisplayStore.getState().setSpectrumReferenceLevel(0);
    const viewport = useDisplayStore.getState().viewport;

    expect(viewport).toMatchObject({ minDbm: -100, maxDbm: 0 });
    expect(spectrumAmplitudeTicks(viewport)[0]).toBe(0);
  });

  it("updates both labels and absolute-dBm mapping for a -20 dBm reference", () => {
    useDisplayStore.getState().setSpectrumReferenceLevel(-20);
    const viewport = useDisplayStore.getState().viewport;
    const ticks = spectrumAmplitudeTicks(viewport);

    expect(ticks[0]).toBe(-20);
    expect(ticks.at(-1)).toBe(-120);
    expect(spectrumAmplitudeFraction(-20, viewport)).toBe(1);
    expect(spectrumAmplitudeFraction(-70, viewport)).toBe(0.5);
  });
});
