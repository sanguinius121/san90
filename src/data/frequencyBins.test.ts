import {describe,expect,it} from 'vitest'
import {spectrumBinFrequencyHz} from './frequencyBins'

describe('coarse hardware frequency bins',()=>{
  it('maps 26 measured bins using actual span/point-count spacing',()=>{
    const frame={startHz:2_399_218_750,stopHz:2_500_781_250,values:new Float32Array(26)}
    expect(spectrumBinFrequencyHz(frame,0)).toBeCloseTo(2_401_171_875)
    expect(spectrumBinFrequencyHz(frame,25)).toBeCloseTo(2_498_828_125)
    expect(spectrumBinFrequencyHz(frame,1)-spectrumBinFrequencyHz(frame,0)).toBe(3_906_250)
  })
  it('never fabricates an interpolated marker bin',()=>{
    expect(()=>spectrumBinFrequencyHz({startHz:0,stopHz:1,values:new Float32Array(26)},26)).toThrow(/outside/)
  })
})
