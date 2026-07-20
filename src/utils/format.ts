export const formatFrequency = (hz: number, precision = 4) => {
  if (Math.abs(hz) >= 1e9) return `${(hz / 1e9).toFixed(precision)} GHz`
  if (Math.abs(hz) >= 1e6) return `${(hz / 1e6).toFixed(precision > 2 ? 2 : precision)} MHz`
  if (Math.abs(hz) >= 1e3) return `${(hz / 1e3).toFixed(2)} kHz`
  return `${hz.toFixed(0)} Hz`
}
export const shortFrequency = (hz: number) => hz >= 1e9 ? `${(hz / 1e9).toFixed(3)}G` : hz >= 1e6 ? `${(hz / 1e6).toFixed(3)}M` : `${(hz / 1e3).toFixed(1)}k`
export const formatDuration = (ms: number) => ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms.toFixed(0)}ms`
