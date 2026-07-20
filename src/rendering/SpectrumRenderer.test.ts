import {describe,expect,it} from 'vitest'
import {accumulateSpectrumIntervalMax,mergePendingSpectrum} from './SpectrumRenderer'
import {fixedRenderDecision} from './renderSchedule'

describe('bounded spectrum temporal summary',()=>{
  it('retains peaks from every published trace until rendering',()=>{
    let summary:Float32Array|null=null
    summary=accumulateSpectrumIntervalMax(summary,new Float32Array([-90,-40,-80]))
    summary=accumulateSpectrumIntervalMax(summary,new Float32Array([-70,-60,-30]))
    summary=accumulateSpectrumIntervalMax(summary,new Float32Array([-80,-20,-50]))
    expect(Array.from(summary)).toEqual([-70,-20,-30])
  })
  it('resizes atomically when point count changes',()=>{
    const summary=accumulateSpectrumIntervalMax(new Float32Array([1,2]),new Float32Array([3,4,5]))
    expect(Array.from(summary)).toEqual([3,4,5])
  })
  it('keeps newest current while merging all pending interval maxima',()=>{
    let pending=mergePendingSpectrum(null,new Float32Array([1,2]),new Float32Array([9,2]))
    pending=mergePendingSpectrum(pending,new Float32Array([3,4]),new Float32Array([3,8]))
    expect(Array.from(pending.latest)).toEqual([3,4]);expect(Array.from(pending.maximum)).toEqual([9,8]);expect(pending.framesMerged).toBe(2)
  })
  it('uses a drift-free 60 Hz deadline grid on a 100 Hz display',()=>{
    let deadline=0,renders=0
    for(let now=10;now<=1000;now+=10){const decision=fixedRenderDecision(now,deadline);deadline=decision.nextDeadline;if(decision.due)renders++}
    expect(renders).toBeGreaterThanOrEqual(59)
    expect(renders).toBeLessThanOrEqual(61)
  })
})
