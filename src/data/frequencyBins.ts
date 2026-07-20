import type { SpectrumFrame } from '../types'

export function spectrumBinFrequencyHz(frame:Pick<SpectrumFrame,'startHz'|'stopHz'|'values'>,bin:number):number{
  if(frame.values.length<1||!Number.isInteger(bin)||bin<0||bin>=frame.values.length)throw new Error('Spectrum bin is outside the measured trace')
  return frame.startHz+(bin+.5)*(frame.stopHz-frame.startHz)/frame.values.length
}
