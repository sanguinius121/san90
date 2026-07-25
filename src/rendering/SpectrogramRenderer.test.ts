import { describe,expect,it } from 'vitest'
import { BoundedWaterfallBatchBuffer,CircularWaterfallCursor,chronologicalTextureRow,debugWaterfallRows,planCircularRowUploads,sourceAgeRangeForOutputRow,spectrogramStateTransition,verticalMaxPoolCircularRows,verticalMaxPoolRows,visibleTextureRow,waterfallHistorySeconds,waterfallVisibleRows } from './SpectrogramRenderer'

describe('batched waterfall texture planning',()=>{
  it('uses one partial upload when a batch does not wrap',()=>{
    expect(planCircularRowUploads(100,4,2048)).toEqual([{sourceRowOffset:0,targetRow:100,rowCount:4}])
  })
  it('splits a four-row batch across the circular boundary in order',()=>{
    expect(planCircularRowUploads(2046,4,2048)).toEqual([
      {sourceRowOffset:0,targetRow:2046,rowCount:2},
      {sourceRowOffset:2,targetRow:0,rowCount:2},
    ])
  })
  it('keeps all eight rows ordered across a texture wrap',()=>{
    expect(planCircularRowUploads(4092,8,4096)).toEqual([
      {sourceRowOffset:0,targetRow:4092,rowCount:4},
      {sourceRowOffset:4,targetRow:0,rowCount:4},
    ])
  })
  it('splits one-row and eight-row boundary uploads oldest to newest',()=>{
    expect(planCircularRowUploads(7,1,8)).toEqual([{sourceRowOffset:0,targetRow:7,rowCount:1}])
    expect(planCircularRowUploads(7,8,8)).toEqual([{sourceRowOffset:0,targetRow:7,rowCount:1},{sourceRowOffset:1,targetRow:0,rowCount:7}])
  })
  it('supports dynamic batch sizes and rejects impossible uploads',()=>{
    expect(planCircularRowUploads(2047,1,2048)).toHaveLength(1)
    expect(()=>planCircularRowUploads(0,2049,2048)).toThrow(/Invalid circular/)
  })
  it('calculates time-axis history from row rate rather than render FPS',()=>{
    expect(waterfallHistorySeconds(2048,240)).toBeCloseTo(8.5333,3)
    expect(waterfallHistorySeconds(2048,60)).toBeCloseTo(34.1333,3)
  })
  it('keeps the visible time span fixed at five seconds for adaptive row rates',()=>{
    expect([60,120,240,480].map(rate=>waterfallVisibleRows(rate,5))).toEqual([300,600,1200,2400])
    expect(waterfallHistorySeconds(4096,480)).toBeGreaterThan(5)
  })
  it('samples only the newest visible rows in correct circular order',()=>{
    expect(visibleTextureRow(100,0,1200,4096)).toBe(99)
    expect(visibleTextureRow(100,1,1200,4096)).toBe(2996)
    expect(visibleTextureRow(0,0,300,4096)).toBe(4095)
  })
  it('maps a five-second 300-row viewport across the full 442-pixel height',()=>{
    const ranges=Array.from({length:442},(_,row)=>sourceAgeRangeForOutputRow(row,442,300))
    expect(ranges[0]).toEqual({start:0,end:1})
    expect(ranges.at(-1)).toEqual({start:299,end:300})
    expect(new Set(ranges.flatMap(range=>Array.from({length:range.end-range.start},(_,offset)=>range.start+offset))).size).toBe(300)
  })
  it('keeps chronological texture rows monotonic through wrap',()=>{
    expect(Array.from({length:6},(_,age)=>chronologicalTextureRow(2,age,8))).toEqual([1,0,7,6,5,4])
  })
  it('max-pools one output bin across the circular boundary',()=>{
    const texture=new Uint8Array([4,1,1,1,1,1,1,250])
    expect(Array.from(verticalMaxPoolCircularRows(texture,8,1,1,4,2))).toEqual([250,1])
  })
  it('tracks only written rows and resets validity on generation reset',()=>{
    const cursor=new CircularWaterfallCursor(16)
    cursor.commit(4);expect([cursor.writeRow,cursor.validRows,cursor.wraps]).toEqual([4,4,0])
    cursor.commit(12);expect([cursor.writeRow,cursor.validRows,cursor.wraps]).toEqual([0,16,1])
    cursor.reset();expect([cursor.writeRow,cursor.validRows,cursor.wraps]).toEqual([0,0,0])
  })
  it('resets history once per new generation without reallocating an unchanged texture',()=>{
    expect(spectrogramStateTransition(7,3328,8,3328)).toEqual({
      generationChanged:true,
      pointCountChanged:false,
      resetHistory:true,
      reallocateTexture:false,
    })
    expect(spectrogramStateTransition(8,3328,8,3328)).toEqual({
      generationChanged:false,
      pointCountChanged:false,
      resetHistory:false,
      reallocateTexture:false,
    })
  })
  it('reallocates only for a genuine point-count change and avoids a duplicate history reset',()=>{
    expect(spectrogramStateTransition(8,3328,9,1664)).toEqual({
      generationChanged:true,
      pointCountChanged:true,
      resetHistory:false,
      reallocateTexture:true,
    })
  })
  it('commits multiple queued wrap batches without duplicated texture targets',()=>{
    const cursor=new CircularWaterfallCursor(16);cursor.commit(12)
    expect(cursor.plan(8)).toEqual([{sourceRowOffset:0,targetRow:12,rowCount:4},{sourceRowOffset:4,targetRow:0,rowCount:4}]);cursor.commit(8)
    expect(cursor.plan(8)).toEqual([{sourceRowOffset:0,targetRow:4,rowCount:8}]);cursor.commit(8)
    expect([cursor.writeRow,cursor.validRows,cursor.wraps]).toEqual([12,16,1])
  })
  it('encodes row sequences for visual ordering debug mode',()=>{
    const rows=debugWaterfallRows(4,3,254)
    expect(Array.from(rows)).toEqual([255,255,255,1,1,1,2,2,2,3,3,3])
  })
  it('uses vertical max pooling so a one-row transient survives compression',()=>{
    const source=new Uint8Array([1,2,3,4,250,6,7,8])
    expect(Array.from(verticalMaxPoolRows(source,4,2,2))).toEqual([3,4,250,8])
  })
  it('max-pools native 52-point rows without inventing horizontal bins',()=>{
    const source=new Uint8Array(4*52);source[2*52+17]=255
    const pooled=verticalMaxPoolRows(source,4,52,2)
    expect(pooled).toHaveLength(2*52);expect(pooled[52+17]).toBe(255)
  })
  it('keeps pending waterfall batches bounded and peak-preserving',()=>{
    const buffer=new BoundedWaterfallBatchBuffer(2)
    const batch=(sequence:number,value:number)=>({sequence,batchSequence:sequence,firstRowSequence:sequence,rowCount:1,pointCount:2,nominalRowPeriodNs:1n,source:'simulator' as const,deviceTimestampNs:0n,hostTimestampNs:0n,startHz:1,centerHz:2,stopHz:3,spanHz:2,rbwHz:1,referenceLevelDbm:0,configurationGeneration:1,values:new Uint8Array([value,1])})
    buffer.push(batch(1,240));buffer.push(batch(2,2));buffer.push(batch(3,3))
    const pending=buffer.drain();expect(pending).toHaveLength(2);expect(pending[0].values[0]).toBe(240);expect(buffer.replacedBatches).toBe(1);expect(buffer.replacedRows).toBe(1)
  })
  it('drains retained batches in chronological order',()=>{
    const buffer=new BoundedWaterfallBatchBuffer()
    const batch=(sequence:number)=>({sequence,batchSequence:sequence,firstRowSequence:sequence*8,rowCount:8,pointCount:1,nominalRowPeriodNs:1n,source:'san90' as const,deviceTimestampNs:0n,hostTimestampNs:0n,startHz:1,centerHz:2,stopHz:3,spanHz:2,rbwHz:1,referenceLevelDbm:0,configurationGeneration:4,values:new Uint8Array(8).fill(sequence)})
    buffer.push(batch(10));buffer.push(batch(11))
    expect(buffer.drain().map(frame=>frame.batchSequence)).toEqual([10,11])
  })
  it('rejects duplicate and reversed batches without disturbing chronological order',()=>{
    const buffer=new BoundedWaterfallBatchBuffer()
    const batch=(sequence:number)=>({sequence,batchSequence:sequence,firstRowSequence:sequence*4,rowCount:4,pointCount:1,nominalRowPeriodNs:1n,source:'san90' as const,deviceTimestampNs:0n,hostTimestampNs:0n,startHz:1,centerHz:2,stopHz:3,spanHz:2,rbwHz:1,referenceLevelDbm:0,configurationGeneration:8,values:new Uint8Array(4).fill(sequence)})
    buffer.push(batch(20));buffer.push(batch(20));buffer.push(batch(19));buffer.push(batch(21))
    expect(buffer.drain().map(frame=>frame.batchSequence)).toEqual([20,21])
    expect([buffer.outOfOrderBatches,buffer.outOfOrderRows]).toEqual([2,8])
  })
  it('discards queued rows when a new configuration generation starts',()=>{
    const buffer=new BoundedWaterfallBatchBuffer()
    const batch=(generation:number,sequence:number)=>({sequence,batchSequence:sequence,firstRowSequence:sequence,rowCount:1,pointCount:1,nominalRowPeriodNs:1n,source:'san90' as const,deviceTimestampNs:0n,hostTimestampNs:0n,startHz:1,centerHz:2,stopHz:3,spanHz:2,rbwHz:1,referenceLevelDbm:0,configurationGeneration:generation,values:new Uint8Array([sequence])})
    buffer.push(batch(8,100));buffer.push(batch(9,0));buffer.push(batch(9,1))
    expect(buffer.drain().map(frame=>[frame.configurationGeneration,frame.batchSequence])).toEqual([[9,0],[9,1]])
  })
  it('absorbs a sixteen-batch delivery burst without losing rows',()=>{
    const buffer=new BoundedWaterfallBatchBuffer()
    const batch=(sequence:number)=>({sequence,batchSequence:sequence,firstRowSequence:sequence*8,rowCount:8,pointCount:1,nominalRowPeriodNs:1n,source:'san90' as const,deviceTimestampNs:0n,hostTimestampNs:0n,startHz:1,centerHz:2,stopHz:3,spanHz:2,rbwHz:1,referenceLevelDbm:0,configurationGeneration:4,values:new Uint8Array(8).fill(sequence)})
    for(let sequence=0;sequence<16;sequence++)buffer.push(batch(sequence))
    expect(buffer.drain().map(frame=>frame.batchSequence)).toEqual(Array.from({length:16},(_,index)=>index))
    expect([buffer.replacedBatches,buffer.replacedRows]).toEqual([0,0])
  })
})
