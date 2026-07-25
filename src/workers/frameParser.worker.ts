/// <reference lib="webworker" />
import { parseAnalyzerMessage } from '../data/binaryProtocol'

const workerScope = self as unknown as DedicatedWorkerGlobalScope
let currentGeneration = 0
workerScope.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  try {
    const parsed = parseAnalyzerMessage(event.data)
    if (parsed.kind === 'status') currentGeneration = Math.max(currentGeneration, parsed.status.configuration_generation)
    else if (parsed.kind === 'ai-detections') {
      workerScope.postMessage(parsed)
      return
    } else if (parsed.frame.configurationGeneration < currentGeneration) {
      workerScope.postMessage({ rejected: 'stale', kind: parsed.kind })
      return
    } else currentGeneration = parsed.frame.configurationGeneration
    if (parsed.kind === 'spectrum') {
      const transfers:Transferable[]=[parsed.frame.values.buffer]
      if(parsed.frame.intervalMaxValues)transfers.push(parsed.frame.intervalMaxValues.buffer)
      workerScope.postMessage(parsed,transfers)
    }
    else if (parsed.kind === 'waterfall') workerScope.postMessage(parsed, [parsed.frame.values.buffer])
    else workerScope.postMessage(parsed)
  } catch (error) {
    const messageType=event.data.byteLength>5?new DataView(event.data).getUint8(5):null
    workerScope.postMessage({ error: error instanceof Error ? error.message : 'Frame parsing failed', kind:messageType===3?'waterfall':'other' })
  }
}
export {}
