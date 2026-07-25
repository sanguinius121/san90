import { describe, expect, it } from 'vitest'
import { acceptsConfigurationGeneration, parseAnalyzerMessage } from './binaryProtocol'

function frame(messageType: number, pointCount: number): ArrayBuffer {
  const payloadLength = messageType === 1 ? pointCount * 4 : pointCount
  const buffer = new ArrayBuffer(96 + payloadLength)
  const bytes = new Uint8Array(buffer); bytes.set([83, 65, 78, 57])
  const view = new DataView(buffer)
  view.setUint8(4, 2); view.setUint8(5, messageType); view.setUint8(6, 2); view.setUint8(7, messageType === 1 ? 1 : 2)
  view.setUint16(8, 96, true); view.setBigUint64(12, 42n, true); view.setBigUint64(20, 123n, true); view.setBigUint64(28, 456n, true); view.setBigUint64(36, 7n, true)
  view.setUint32(44, pointCount, true); view.setUint32(48, payloadLength, true)
  view.setFloat64(52, 2.399e9, true); view.setFloat64(60, 2.45e9, true); view.setFloat64(68, 2.501e9, true)
  view.setFloat64(76, 102e6, true); view.setFloat64(84, 60_306.091, true); view.setFloat32(92, 0, true)
  if (messageType === 1) for (let index = 0; index < pointCount; index++) view.setFloat32(96 + index * 4, -100 + index / pointCount, true)
  else bytes.fill(127, 96)
  return buffer
}

function waterfallBatch(pointCount:number,rowCount=4):ArrayBuffer{
  const payloadLength=pointCount*rowCount;const buffer=new ArrayBuffer(120+payloadLength);const bytes=new Uint8Array(buffer);bytes.set([83,65,78,57]);const view=new DataView(buffer)
  view.setUint8(4,3);view.setUint8(5,3);view.setUint8(6,1);view.setUint8(7,2);view.setUint16(8,120,true)
  view.setBigUint64(12,9n,true);view.setBigUint64(20,36n,true);view.setBigUint64(28,123n,true);view.setBigUint64(36,456n,true);view.setBigUint64(44,7n,true);view.setBigUint64(52,4_166_667n,true)
  view.setUint32(60,rowCount,true);view.setUint32(64,pointCount,true);view.setUint32(68,payloadLength,true)
  view.setFloat64(76,2.399e9,true);view.setFloat64(84,2.45e9,true);view.setFloat64(92,2.501e9,true);view.setFloat64(100,102e6,true);view.setFloat64(108,241_224.365,true);view.setFloat32(116,0,true)
  for(let row=0;row<rowCount;row++)bytes.fill(20+row,120+row*pointCount,120+(row+1)*pointCount)
  return buffer
}
function temporalSpectrum(pointCount:number):ArrayBuffer{
  const payloadLength=pointCount*8,buffer=new ArrayBuffer(128+payloadLength),bytes=new Uint8Array(buffer),view=new DataView(buffer);bytes.set([83,65,78,57])
  view.setUint8(4,4);view.setUint8(5,2);view.setUint8(6,1);view.setUint8(7,4);view.setUint16(8,128,true)
  view.setBigUint64(12,9n,true);view.setBigUint64(20,10n,true);view.setBigUint64(28,11n,true);view.setBigUint64(36,7n,true);view.setBigUint64(44,100n,true);view.setBigUint64(52,200n,true)
  view.setUint32(60,127,true);view.setUint32(64,pointCount,true);view.setUint32(68,payloadLength,true)
  view.setFloat64(76,2.399e9,true);view.setFloat64(84,2.45e9,true);view.setFloat64(92,2.501e9,true);view.setFloat64(100,102e6,true);view.setFloat64(108,60_306,true);view.setFloat32(116,-10,true);view.setFloat32(120,.5,true);view.setFloat32(124,-120,true)
  for(let index=0;index<pointCount;index++){view.setFloat32(128+index*4,-100,true);view.setFloat32(128+(pointCount+index)*4,index===1?-30:-90,true)}
  return buffer
}

function aiDetections():ArrayBuffer{
  const payload=new TextEncoder().encode(JSON.stringify({
    sequence:12,timestamp_ns:1_784_947_230_410_329_302,generated_at:1_784_947_230.4,received_at_ns:1_784_947_230_420_000_000,
    detections:[{class_id:4,label:'DJI_20MHz',confidence:.86,frequency_start:5.731e9,frequency_stop:5.751e9}],
  }))
  const buffer=new ArrayBuffer(96+payload.length),bytes=new Uint8Array(buffer),view=new DataView(buffer);bytes.set([83,65,78,57]);bytes.set(payload,96)
  view.setUint8(4,2);view.setUint8(5,0x11);view.setUint8(6,2);view.setUint8(7,3);view.setUint16(8,96,true)
  view.setBigUint64(12,12n,true);view.setBigUint64(28,1n,true);view.setUint32(48,payload.length,true)
  view.setFloat64(52,0,true);view.setFloat64(60,0,true);view.setFloat64(68,1,true);view.setFloat64(76,1,true)
  return buffer
}

describe('binary analyzer protocol', () => {
  it('parses an actual 3328-point float32 SAN-90 spectrum', () => {
    const parsed = parseAnalyzerMessage(frame(1, 3328))
    expect(parsed.kind).toBe('spectrum')
    if (parsed.kind !== 'spectrum') return
    expect(parsed.frame.values).toHaveLength(3328)
    expect(parsed.frame.startHz).toBe(2.399e9)
    expect(parsed.frame.stopHz).toBe(2.501e9)
    expect(parsed.frame.rbwHz).toBeCloseTo(60_306.091)
    expect(parsed.frame.configurationGeneration).toBe(7)
  })

  it('parses a 3328-point uint8 waterfall without float conversion', () => {
    const parsed = parseAnalyzerMessage(frame(3, 3328))
    expect(parsed.kind).toBe('waterfall')
    if (parsed.kind !== 'waterfall') return
    expect(parsed.frame.values).toBeInstanceOf(Uint8Array)
    expect(parsed.frame.values).toHaveLength(3328)
  })

  it('accepts a dynamic 832-point spectrum and waterfall', () => {
    const spectrum = parseAnalyzerMessage(frame(1, 832))
    const waterfall = parseAnalyzerMessage(frame(3, 832))
    expect(spectrum.kind).toBe('spectrum')
    expect(waterfall.kind).toBe('waterfall')
    if (spectrum.kind === 'spectrum') expect(spectrum.frame.values).toHaveLength(832)
    if (waterfall.kind === 'waterfall') expect(waterfall.frame.values).toHaveLength(832)
  })

  it('rejects malformed payload lengths', () => {
    const malformed = frame(3, 3328); new DataView(malformed).setUint32(48, 1, true)
    expect(() => parseAnalyzerMessage(malformed)).toThrow(/Payload length/)
  })
  it('rejects frames from an older configuration generation',()=>{
    expect(acceptsConfigurationGeneration(6,7)).toBe(false)
    expect(acceptsConfigurationGeneration(7,7)).toBe(true)
    expect(acceptsConfigurationGeneration(8,7)).toBe(true)
  })

  it.each([832,3328])('parses a contiguous four-row %i-point waterfall batch',(points)=>{
    const parsed=parseAnalyzerMessage(waterfallBatch(points))
    expect(parsed.kind).toBe('waterfall')
    if(parsed.kind!=='waterfall')return
    expect(parsed.frame.rowCount).toBe(4);expect(parsed.frame.pointCount).toBe(points)
    expect(parsed.frame.values).toHaveLength(4*points);expect(parsed.frame.values[0]).toBe(20);expect(parsed.frame.values[points]).toBe(21)
    expect(parsed.frame.firstRowSequence).toBe(36);expect(parsed.frame.nominalRowPeriodNs).toBe(4_166_667n)
  })

  it('rejects zero-row and malformed-length waterfall batches',()=>{
    const zero=waterfallBatch(832);new DataView(zero).setUint32(60,0,true)
    expect(()=>parseAnalyzerMessage(zero)).toThrow(/row count is zero/)
    const malformed=waterfallBatch(832);new DataView(malformed).setUint32(68,1,true)
    expect(()=>parseAnalyzerMessage(malformed)).toThrow(/payload/)
    const noPeriod=waterfallBatch(832);new DataView(noPeriod).setBigUint64(52,0n,true)
    expect(()=>parseAnalyzerMessage(noPeriod)).toThrow(/row period/)
  })

  it('rejects unsupported batch protocol versions',()=>{
    const unsupported=waterfallBatch(832);new DataView(unsupported).setUint8(4,5)
    expect(()=>parseAnalyzerMessage(unsupported)).toThrow(/Unsupported protocol version/)
  })
  it('parses newest and interval-max arrays from a temporal spectrum',()=>{
    const parsed=parseAnalyzerMessage(temporalSpectrum(832));expect(parsed.kind).toBe('spectrum');if(parsed.kind!=='spectrum')return
    expect(parsed.frame.values[1]).toBe(-100);expect(parsed.frame.intervalMaxValues?.[1]).toBe(-30)
    expect(parsed.frame.tracesIntegrated).toBe(127);expect(parsed.frame.intervalStartMonotonicNs).toBe(100n)
  })
  it.each([26,52,104])('preserves every measured bin in a %i-point temporal spectrum',(points)=>{
    const parsed=parseAnalyzerMessage(temporalSpectrum(points));expect(parsed.kind).toBe('spectrum');if(parsed.kind!=='spectrum')return
    expect(parsed.frame.values).toHaveLength(points);expect(parsed.frame.intervalMaxValues).toHaveLength(points)
  })
  it('rejects malformed temporal spectrum dimensions',()=>{
    const malformed=temporalSpectrum(8);new DataView(malformed).setUint32(60,0,true)
    expect(()=>parseAnalyzerMessage(malformed)).toThrow(/dimensions/)
  })
  it('parses current-frame AI frequency detections',()=>{
    const parsed=parseAnalyzerMessage(aiDetections());expect(parsed.kind).toBe('ai-detections');if(parsed.kind!=='ai-detections')return
    expect(parsed.result.sequence).toBe(12)
    expect(parsed.result.detections).toEqual([{classId:4,label:'DJI_20MHz',confidence:.86,frequencyStartHz:5.731e9,frequencyStopHz:5.751e9}])
  })
})
