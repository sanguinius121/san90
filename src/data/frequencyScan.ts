import type { FrequencyScanEntryApi } from './controlApi'
import {
  centerFrequencyPrecision,
  displayValueToHz,
  hzToDisplayValue,
  type CenterFrequencyUnit,
} from './frequencyUnits'

export const DEFAULT_SCAN_DURATION_MS = 5_000
export const MIN_SCAN_DURATION_MS = 500
export const SCAN_DURATION_STEP_MS = 500
export const DEFAULT_SCAN_STEP_HZ = 10e6

export const DEFAULT_FREQUENCY_SCAN_ENTRIES = [
  {frequencyHz:400e6,frequencyUnit:'MHz'},
  {frequencyHz:900e6,frequencyUnit:'MHz'},
  {frequencyHz:2.44e9,frequencyUnit:'GHz'},
  {frequencyHz:3.3e9,frequencyUnit:'GHz'},
  {frequencyHz:5e9,frequencyUnit:'GHz'},
  {frequencyHz:5.775e9,frequencyUnit:'MHz'},
] as const satisfies ReadonlyArray<{
  frequencyHz:number
  frequencyUnit:CenterFrequencyUnit
}>

export interface FrequencyScanDraftEntry {
  id:string
  enabled:boolean
  frequencyHz:number
  frequencyUnit:CenterFrequencyUnit
  frequencyDraft:string
  stepHz:number
  stepUnit:CenterFrequencyUnit
  stepDraft:string
  durationMs:number
  durationDraft:string
}

export function formatScanNumber(value:number, precision:number):string {
  return String(Number(value.toFixed(precision)))
}

export function frequencyDraftFromHz(hz:number, unit:CenterFrequencyUnit):string {
  return formatScanNumber(hzToDisplayValue(hz, unit), centerFrequencyPrecision(unit))
}

export function scanEntryApiFromDraft(
  entry:FrequencyScanDraftEntry,
  minimumFrequencyHz:number,
  maximumFrequencyHz:number,
):FrequencyScanEntryApi|null {
  const frequencyValue=Number(entry.frequencyDraft)
  const frequencyHz=displayValueToHz(frequencyValue,entry.frequencyUnit)
  const stepValue=Number(entry.stepDraft)
  const stepHz=displayValueToHz(stepValue,entry.stepUnit)
  const durationSeconds=Number(entry.durationDraft)
  const durationMs=durationSeconds*1000
  const maximumStepHz=maximumFrequencyHz-minimumFrequencyHz
  if(
    !entry.frequencyDraft.trim()||
    !Number.isFinite(frequencyHz)||
    frequencyHz<=0||
    frequencyHz<minimumFrequencyHz||
    frequencyHz>maximumFrequencyHz||
    !entry.stepDraft.trim()||
    !Number.isFinite(stepHz)||
    stepHz<=0||
    stepHz>maximumStepHz||
    !entry.durationDraft.trim()||
    !Number.isFinite(durationMs)||
    !Number.isInteger(durationMs)||
    durationMs<MIN_SCAN_DURATION_MS
  )return null
  return {
    id:entry.id,
    enabled:entry.enabled,
    center_frequency_hz:frequencyHz,
    duration_ms:durationMs,
    duration_seconds:durationMs/1000,
    step_hz:stepHz,
    display_unit:entry.frequencyUnit,
    step_unit:entry.stepUnit,
  }
}

export function validateFrequencyScanDrafts(
  entries:FrequencyScanDraftEntry[],
  minimumFrequencyHz:number,
  maximumFrequencyHz:number,
):FrequencyScanEntryApi[] | null {
  const result:FrequencyScanEntryApi[]=[]
  for(const entry of entries){
    const validated=scanEntryApiFromDraft(entry,minimumFrequencyHz,maximumFrequencyHz)
    if(!validated)return null
    result.push(validated)
  }
  return result
}
