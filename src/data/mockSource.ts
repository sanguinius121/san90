import { liveFrames } from './liveFrames'
import { useDeviceStore, useRuntimeStore } from '../stores'

const DISPLAY_FPS = 60
const gaussian = (x: number, center: number, width: number) => Math.exp(-0.5 * ((x - center) / width) ** 2)

export interface MockTemporalBatch{latest:Float32Array;maximum:Float32Array;waterfallRows:Uint8Array;tracesIntegrated:number}
export function generateMockTemporalBatch(points:number,phase:number,referenceDbm:number,rowCount:number,amplitudeOffsetDb=0):MockTemporalBatch{
  if(points<2||rowCount<1)throw new Error('Invalid mock temporal dimensions')
  const nativeCount=Math.max(8,rowCount),latest=new Float32Array(points),maximum=new Float32Array(points).fill(-Infinity)
  const waterfallRows=new Uint8Array(rowCount*points)
  const hops=[0.12,0.24,0.38,0.67,0.82]
  for(let trace=0;trace<nativeCount;trace++){
    const t=phase+trace/nativeCount
    const activeHop=hops[Math.floor(phase)%hops.length]
    const targetRow=Math.min(rowCount-1,Math.floor(trace*rowCount/nativeCount))
    for(let i=0;i<points;i++){
      const x=i/(points-1)
      let db=-101+Math.random()*8+Math.sin(i*.31+t)*1.1
      db=Math.max(db,-48+1.8*Math.sin(t*.13)-55*Math.abs(x-.285))
      db=Math.max(db,-52-16*((x-.52)/.075)**4+Math.random()*2)
      db=Math.max(db,-43+2*Math.sin(t*.08)-9000*(x-.742)**2)
      db=Math.max(db,-59-12000*(x-.135)**2)
      // Exactly one native trace: shorter than the 60 Hz display interval.
      if(trace===2)db=Math.max(db,-43+62*gaussian(x,activeHop,.0035))
      if((Math.floor(t)%13)<6)db=Math.max(db,-72+15*gaussian(x,.61+Math.sin(t*.11)*.018,.012))
      db+=amplitudeOffsetDb
      maximum[i]=Math.max(maximum[i],db)
      if(trace===nativeCount-1)latest[i]=db
      const code=Math.max(0,Math.min(255,Math.round(((db+112)/(referenceDbm+112))*255)))
      const offset=targetRow*points+i
      if(code>waterfallRows[offset])waterfallRows[offset]=code
    }
  }
  return{latest,maximum,waterfallRows,tracesIntegrated:nativeCount}
}

export class MockSpectrumSource {
  private timer: number | null = null
  private sequence = 0
  private phase = 0
  private frameTimes: number[] = []
  private generation = 1
  start() {
    if (this.timer !== null) return
    const debugOverflow =
      new URLSearchParams(location.search).get("ifOverflow") === "1" ||
      import.meta.env.VITE_SIMULATOR_IF_OVERFLOW === "true";
    useRuntimeStore.getState().update({ source:'simulator', connection: 'mock', lastError: undefined, ifOverflow: debugOverflow })
    this.timer = window.setInterval(() => this.generate(), 1000 / DISPLAY_FPS)
  }
  stop() { if (this.timer !== null) window.clearInterval(this.timer); this.timer = null; useRuntimeStore.getState().update({ifOverflow:false}) }
  private generate() {
    try {
      const { centerHz, spanHz, referenceDbm, amplitudeOffsetDb } = useDeviceStore.getState();const runtime=useRuntimeStore.getState();const points=runtime.pointCount
      const t = this.phase
      const rowCount=runtime.waterfallRowsPerBatch
      const temporal=generateMockTemporalBatch(points,t,referenceDbm,rowCount,amplitudeOffsetDb)
      const now = performance.now()
      this.frameTimes.push(now); while (this.frameTimes[0] < now - 1000) this.frameTimes.shift()
      useRuntimeStore.getState().update({ fps: this.frameTimes.length, spectrumFps:this.frameTimes.length, waterfallFps:runtime.waterfallRowsPerSecond,waterfallBatchFps:60, actualSpanHz:spanHz, actualRbwHz:useDeviceStore.getState().rbwHz })
      const generation=runtime.configurationGeneration||this.generation;const sequence=this.sequence++
      const intervalEnd=BigInt(Math.round(performance.now()*1e6)),intervalStart=intervalEnd-BigInt(Math.round(1e9/DISPLAY_FPS))
      liveFrames.publish({ sequence, timestamp: Date.now(), source: 'simulator', configurationGeneration:generation, startHz: centerHz - spanHz / 2, centerHz, stopHz: centerHz + spanHz / 2, spanHz, rbwHz: useDeviceStore.getState().rbwHz, referenceLevelDbm: referenceDbm, values:temporal.latest,intervalMaxValues:temporal.maximum,intervalStartMonotonicNs:intervalStart,intervalEndMonotonicNs:intervalEnd,tracesIntegrated:temporal.tracesIntegrated,waterfall:new Uint8Array() })
      liveFrames.publishWaterfall({sequence,batchSequence:sequence,firstRowSequence:sequence*rowCount,rowCount,pointCount:points,nominalRowPeriodNs:BigInt(Math.round(1e9/runtime.waterfallRowsPerSecond)),source:'simulator',deviceTimestampNs:0n,hostTimestampNs:BigInt(Date.now())*1000000n,startHz:centerHz-spanHz/2,centerHz,stopHz:centerHz+spanHz/2,spanHz,rbwHz:useDeviceStore.getState().rbwHz,referenceLevelDbm:referenceDbm,configurationGeneration:generation,values:temporal.waterfallRows})
      this.phase++
    } catch (error) {
      useRuntimeStore.getState().update({ connection: 'error', lastError: error instanceof Error ? error.message : 'Mock source failed' })
      this.stop()
    }
  }
}
