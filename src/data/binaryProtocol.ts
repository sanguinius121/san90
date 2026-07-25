import type { AiDetectionResult, AnalyzerRuntimeStatus, AnalyzerSourceType, SpectrumFrame, WaterfallFrame } from '../types'

const MAGIC = 'SAN9'
const LEGACY_VERSION = 2
const BATCH_VERSION = 3
const TEMPORAL_SPECTRUM_VERSION = 4
const HEADER_SIZE = 96
const BATCH_HEADER_SIZE = 120
export const TEMPORAL_SPECTRUM_HEADER_SIZE = 128

export type ParsedAnalyzerMessage =
  | { kind: 'spectrum'; frame: SpectrumFrame }
  | { kind: 'waterfall'; frame: WaterfallFrame }
  | { kind: 'ai-detections'; result: AiDetectionResult }
  | { kind: 'status'; status: AnalyzerRuntimeStatus }

export const acceptsConfigurationGeneration=(incoming:number,current:number)=>incoming>=current

function sourceName(code: number): AnalyzerSourceType {
  if (code === 1) return 'simulator'
  if (code === 2) return 'san90'
  throw new Error(`Unknown analyzer source ${code}`)
}

function parseAiDetectionResult(payload: Uint8Array): AiDetectionResult {
  const raw = JSON.parse(new TextDecoder().decode(payload)) as unknown
  if (typeof raw !== 'object' || raw === null) throw new Error('AI detection payload must be an object')
  const data = raw as Record<string, unknown>
  if (!Array.isArray(data.detections)) throw new Error('AI detection payload must contain detections')
  const detections = data.detections.map((item) => {
    if (typeof item !== 'object' || item === null) throw new Error('AI detection entry must be an object')
    const detection = item as Record<string, unknown>
    const label = detection.label
    const confidence = detection.confidence
    const frequencyStartHz = detection.frequency_start
    const frequencyStopHz = detection.frequency_stop
    if (
      typeof label !== 'string' ||
      !label ||
      typeof confidence !== 'number' ||
      !Number.isFinite(confidence) ||
      confidence < 0 ||
      confidence > 1 ||
      typeof frequencyStartHz !== 'number' ||
      !Number.isFinite(frequencyStartHz) ||
      typeof frequencyStopHz !== 'number' ||
      !Number.isFinite(frequencyStopHz) ||
      frequencyStopHz <= frequencyStartHz
    ) throw new Error('AI detection entry is invalid')
    return {
      label,
      confidence,
      frequencyStartHz,
      frequencyStopHz,
      ...(typeof detection.class_id === 'number' && Number.isInteger(detection.class_id)
        ? { classId: detection.class_id }
        : {}),
    }
  })
  const optionalNumber = (name: string) => (
    typeof data[name] === 'number' && Number.isFinite(data[name])
      ? data[name] as number
      : null
  )
  return {
    sequence: optionalNumber('sequence'),
    timestampNs: optionalNumber('timestamp_ns'),
    generatedAt: optionalNumber('generated_at'),
    receivedAtNs: optionalNumber('received_at_ns'),
    detections,
  }
}

export function parseAnalyzerMessage(buffer: ArrayBuffer): ParsedAnalyzerMessage {
  if (buffer.byteLength < HEADER_SIZE) throw new Error(`Frame is shorter than ${HEADER_SIZE}-byte header`)
  const view = new DataView(buffer)
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4))
  if (magic !== MAGIC) throw new Error(`Invalid protocol magic ${JSON.stringify(magic)}`)
  const version = view.getUint8(4)
  if (version !== LEGACY_VERSION && version !== BATCH_VERSION && version !== TEMPORAL_SPECTRUM_VERSION) throw new Error(`Unsupported protocol version ${version}`)
  const messageType = view.getUint8(5)
  const source = sourceName(view.getUint8(6))
  const payloadType = view.getUint8(7)
  const headerSize = view.getUint16(8, true)
  if(version===TEMPORAL_SPECTRUM_VERSION){
    if(messageType!==0x02||payloadType!==4||headerSize!==TEMPORAL_SPECTRUM_HEADER_SIZE)throw new Error('Invalid temporal spectrum protocol identity')
    if(buffer.byteLength<TEMPORAL_SPECTRUM_HEADER_SIZE)throw new Error(`Frame is shorter than ${TEMPORAL_SPECTRUM_HEADER_SIZE}-byte temporal header`)
    const sequence=view.getBigUint64(12,true),deviceTimestampNs=view.getBigUint64(20,true),hostTimestampNs=view.getBigUint64(28,true)
    const generationBig=view.getBigUint64(36,true),intervalStart=view.getBigUint64(44,true),intervalEnd=view.getBigUint64(52,true)
    const tracesIntegrated=view.getUint32(60,true),pointCount=view.getUint32(64,true),payloadLength=view.getUint32(68,true)
    if(pointCount<2||tracesIntegrated<1)throw new Error('Invalid temporal spectrum dimensions')
    if(intervalEnd<intervalStart)throw new Error('Invalid temporal spectrum interval')
    if(payloadLength!==pointCount*8||headerSize+payloadLength!==buffer.byteLength)throw new Error('Invalid temporal spectrum payload dimensions')
    const metadata={startHz:view.getFloat64(76,true),centerHz:view.getFloat64(84,true),stopHz:view.getFloat64(92,true),spanHz:view.getFloat64(100,true),rbwHz:view.getFloat64(108,true),referenceLevelDbm:view.getFloat32(116,true),scaleToDbm:view.getFloat32(120,true),offsetToDbm:view.getFloat32(124,true)}
    if(!Object.values(metadata).every(Number.isFinite))throw new Error('Frame contains non-finite metadata')
    const values=new Float32Array(pointCount),intervalMaxValues=new Float32Array(pointCount)
    for(let index=0;index<pointCount;index++){
      values[index]=view.getFloat32(headerSize+index*4,true)
      intervalMaxValues[index]=view.getFloat32(headerSize+(pointCount+index)*4,true)
      if(!Number.isFinite(values[index])||!Number.isFinite(intervalMaxValues[index]))throw new Error('Temporal spectrum payload contains non-finite values')
    }
    const sequenceNumber=Number(sequence<=BigInt(Number.MAX_SAFE_INTEGER)?sequence:0n)
    const configurationGeneration=Number(generationBig<=BigInt(Number.MAX_SAFE_INTEGER)?generationBig:0n)
    return {kind:'spectrum',frame:{sequence:sequenceNumber,timestamp:Number(hostTimestampNs)/1e6,deviceTimestampNs,hostTimestampNs,source,configurationGeneration,...metadata,intervalStartMonotonicNs:intervalStart,intervalEndMonotonicNs:intervalEnd,tracesIntegrated,values,intervalMaxValues,waterfall:new Uint8Array()}}
  }
  if (version === BATCH_VERSION) {
    if (messageType !== 0x03 || headerSize !== BATCH_HEADER_SIZE) throw new Error(`Unsupported version-3 message or header size ${headerSize}`)
    if (buffer.byteLength < BATCH_HEADER_SIZE) throw new Error(`Frame is shorter than ${BATCH_HEADER_SIZE}-byte batch header`)
    const batchSequence = view.getBigUint64(12, true)
    const firstRowSequence = view.getBigUint64(20, true)
    const deviceTimestampNs = view.getBigUint64(28, true)
    const hostTimestampNs = view.getBigUint64(36, true)
    const configurationGenerationBig = view.getBigUint64(44, true)
    const nominalRowPeriodNs = view.getBigUint64(52, true)
    const rowCount = view.getUint32(60, true)
    const pointCount = view.getUint32(64, true)
    const payloadLength = view.getUint32(68, true)
    if (rowCount === 0) throw new Error('Waterfall batch row count is zero')
    if (pointCount === 0) throw new Error('Trace point count is zero')
    if (nominalRowPeriodNs === 0n) throw new Error('Waterfall batch row period is zero')
    if (payloadType !== 2 || payloadLength !== rowCount * pointCount) throw new Error('Invalid uint8 waterfall batch payload')
    if (headerSize + payloadLength !== buffer.byteLength) throw new Error('Payload length does not match frame size')
    const metadata = {
      startHz: view.getFloat64(76, true), centerHz: view.getFloat64(84, true), stopHz: view.getFloat64(92, true),
      spanHz: view.getFloat64(100, true), rbwHz: view.getFloat64(108, true), referenceLevelDbm: view.getFloat32(116, true),
    }
    if (![metadata.startHz, metadata.centerHz, metadata.stopHz, metadata.spanHz, metadata.rbwHz, metadata.referenceLevelDbm].every(Number.isFinite)) throw new Error('Frame contains non-finite metadata')
    const sequenceNumber = Number(batchSequence <= BigInt(Number.MAX_SAFE_INTEGER) ? batchSequence : 0n)
    const firstRowSequenceNumber = Number(firstRowSequence <= BigInt(Number.MAX_SAFE_INTEGER) ? firstRowSequence : 0n)
    const configurationGeneration = Number(configurationGenerationBig <= BigInt(Number.MAX_SAFE_INTEGER) ? configurationGenerationBig : 0n)
    return { kind: 'waterfall', frame: {
      sequence: sequenceNumber, batchSequence: sequenceNumber, firstRowSequence: firstRowSequenceNumber,
      rowCount, pointCount, nominalRowPeriodNs, source, deviceTimestampNs, hostTimestampNs,
      configurationGeneration, ...metadata, values: new Uint8Array(buffer, headerSize, payloadLength),
    } }
  }
  if (headerSize !== HEADER_SIZE) throw new Error(`Unsupported header size ${headerSize}`)
  const sequence = view.getBigUint64(12, true)
  const deviceTimestampNs = view.getBigUint64(20, true)
  const hostTimestampNs = view.getBigUint64(28, true)
  const configurationGenerationBig = view.getBigUint64(36, true)
  const pointCount = view.getUint32(44, true)
  const payloadLength = view.getUint32(48, true)
  if (headerSize + payloadLength !== buffer.byteLength) throw new Error('Payload length does not match frame size')
  const metadata = {
    startHz: view.getFloat64(52, true), centerHz: view.getFloat64(60, true), stopHz: view.getFloat64(68, true),
    spanHz: view.getFloat64(76, true), rbwHz: view.getFloat64(84, true), referenceLevelDbm: view.getFloat32(92, true),
  }
  if (![metadata.startHz, metadata.centerHz, metadata.stopHz, metadata.spanHz, metadata.rbwHz, metadata.referenceLevelDbm].every(Number.isFinite)) {
    throw new Error('Frame contains non-finite metadata')
  }
  if (messageType === 0x10) {
    if (payloadType !== 3 || pointCount !== 0) throw new Error('Invalid runtime status encoding')
    return { kind: 'status', status: JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, headerSize, payloadLength))) as AnalyzerRuntimeStatus }
  }
  if (messageType === 0x11) {
    if (payloadType !== 3 || pointCount !== 0) throw new Error('Invalid AI detection encoding')
    return {
      kind: 'ai-detections',
      result: parseAiDetectionResult(new Uint8Array(buffer, headerSize, payloadLength)),
    }
  }
  if (pointCount === 0) throw new Error('Trace point count is zero')
  const sequenceNumber = Number(sequence <= BigInt(Number.MAX_SAFE_INTEGER) ? sequence : 0n)
  const configurationGeneration = Number(configurationGenerationBig <= BigInt(Number.MAX_SAFE_INTEGER) ? configurationGenerationBig : 0n)
  if (messageType === 0x01) {
    if (payloadType !== 1 || payloadLength !== pointCount * 4) throw new Error('Invalid float32 spectrum payload')
    const values = new Float32Array(pointCount)
    for (let index = 0; index < pointCount; index++) values[index] = view.getFloat32(headerSize + index * 4, true)
    return { kind: 'spectrum', frame: { sequence: sequenceNumber, timestamp: Number(hostTimestampNs) / 1e6, deviceTimestampNs, hostTimestampNs, source, configurationGeneration, ...metadata, values, waterfall: new Uint8Array() } }
  }
  if (messageType === 0x03) {
    if (payloadType !== 2 || payloadLength !== pointCount) throw new Error('Invalid uint8 waterfall payload')
    const values = new Uint8Array(buffer, headerSize, payloadLength)
    return { kind: 'waterfall', frame: { sequence: sequenceNumber, batchSequence:sequenceNumber, firstRowSequence:sequenceNumber, rowCount:1, pointCount, nominalRowPeriodNs:0n, source, deviceTimestampNs, hostTimestampNs, configurationGeneration, ...metadata, values } }
  }
  throw new Error(`Unsupported message type 0x${messageType.toString(16)}`)
}
