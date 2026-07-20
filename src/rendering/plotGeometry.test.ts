import {describe,expect,it} from 'vitest'
import {frequencyToPlotX,plotRectFramebuffer,plotXToNormalizedFrequency,sharedHorizontalPlotRect} from './plotGeometry'

describe('shared horizontal plot rectangle',()=>{
  it('maps start, center, and stop identically for both panels',()=>{
    const spectrum=sharedHorizontalPlotRect(1431),spectrogram=sharedHorizontalPlotRect(1431)
    expect(spectrum).toEqual(spectrogram)
    expect(frequencyToPlotX(2.4e9,2.4e9,2.5e9,spectrum)).toBe(spectrum.left)
    expect(frequencyToPlotX(2.45e9,2.4e9,2.5e9,spectrum)).toBeCloseTo((spectrum.left+spectrum.right)/2)
    expect(frequencyToPlotX(2.5e9,2.4e9,2.5e9,spectrum)).toBe(spectrum.right)
  })
  it('keeps CSS geometry stable while scaling only framebuffer coordinates',()=>{
    expect(plotRectFramebuffer(1000,1000)).toEqual({left:48,right:990,width:942})
    expect(plotRectFramebuffer(1000,2000)).toEqual({left:96,right:1980,width:1884})
    expect(plotXToNormalizedFrequency(519,sharedHorizontalPlotRect(1000))).toBeCloseTo(.5)
  })
  it('recomputes both edges consistently after resize',()=>{
    expect(sharedHorizontalPlotRect(800)).toEqual({left:48,right:790,width:742})
    expect(sharedHorizontalPlotRect(1200)).toEqual({left:48,right:1190,width:1142})
  })
  it('uses the same transform for grid, marker, and cursor frequencies',()=>{
    const rect=sharedHorizontalPlotRect(1600)
    const markerX=frequencyToPlotX(2.475e9,2.4e9,2.5e9,rect)
    const gridX=rect.left+rect.width*.75
    expect(markerX).toBeCloseTo(gridX)
    expect(plotXToNormalizedFrequency(markerX,rect)).toBeCloseTo(.75)
  })
})
