import {describe,expect,it,vi} from 'vitest'
import {generateMockTemporalBatch} from './mockSource'

describe('browser temporal simulator',()=>{
  it('retains a sub-display-interval hop in max and waterfall',()=>{
    vi.spyOn(Math,'random').mockReturnValue(.5)
    const batch=generateMockTemporalBatch(1024,0,-10,4)
    const hopBin=Math.round(.12*1023)
    expect(batch.tracesIntegrated).toBe(8)
    expect(batch.maximum[hopBin]-batch.latest[hopBin]).toBeGreaterThan(10)
    expect(Math.max(...[0,1,2,3].map(row=>batch.waterfallRows[row*1024+hopBin]))).toBeGreaterThan(150)
    vi.restoreAllMocks()
  })
  it('supports all adaptive waterfall batch sizes without changing spectrum cadence',()=>{
    for(const rows of [1,2,4,8]){
      const batch=generateMockTemporalBatch(208,1,-10,rows)
      expect(batch.latest).toHaveLength(208);expect(batch.maximum).toHaveLength(208);expect(batch.waterfallRows).toHaveLength(rows*208)
    }
  })
})
