import type { FrequencyScanEntryApi } from './controlApi'
import {
  centerFrequencyPrecision,
  displayValueToHz,
  hzToDisplayValue,
  type CenterFrequencyUnit,
} from './frequencyUnits'

export const DEFAULT_SCAN_DURATION_SECONDS = 5
export const MIN_SCAN_DURATION_SECONDS = 0.5
export const SCAN_DURATION_STEP_SECONDS = 0.5

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
  durationSeconds:number
  durationDraft:string
}

export function formatScanNumber(value:number, precision:number):string {
  return String(Number(value.toFixed(precision)))
}

export function frequencyDraftFromHz(hz:number, unit:CenterFrequencyUnit):string {
  return formatScanNumber(hzToDisplayValue(hz, unit), centerFrequencyPrecision(unit))
}

export function validateFrequencyScanDrafts(
  entries:FrequencyScanDraftEntry[],
  minimumFrequencyHz:number,
  maximumFrequencyHz:number,
):FrequencyScanEntryApi[] | null {
  const result:FrequencyScanEntryApi[]=[]
  for(const entry of entries){
    const frequencyValue=Number(entry.frequencyDraft)
    const draftFrequencyHz=displayValueToHz(frequencyValue,entry.frequencyUnit)
    const draftDurationSeconds=Number(entry.durationDraft)
    const frequencyDraftValid=Boolean(entry.frequencyDraft.trim())&&
      Number.isFinite(draftFrequencyHz)&&
      draftFrequencyHz>0&&
      draftFrequencyHz>=minimumFrequencyHz&&
      draftFrequencyHz<=maximumFrequencyHz
    const durationDraftValid=Boolean(entry.durationDraft.trim())&&
      Number.isFinite(draftDurationSeconds)&&
      draftDurationSeconds>=MIN_SCAN_DURATION_SECONDS
    if(entry.enabled&&(!frequencyDraftValid||!durationDraftValid))return null
    const frequencyHz=frequencyDraftValid?draftFrequencyHz:entry.frequencyHz
    const durationSeconds=durationDraftValid?draftDurationSeconds:entry.durationSeconds
    if(
      !Number.isFinite(frequencyHz)||
      frequencyHz<=0||
      frequencyHz<minimumFrequencyHz||
      frequencyHz>maximumFrequencyHz||
      !Number.isFinite(durationSeconds)||
      durationSeconds<MIN_SCAN_DURATION_SECONDS
    )return null
    result.push({
      id:entry.id,
      enabled:entry.enabled,
      center_frequency_hz:frequencyHz,
      duration_seconds:durationSeconds,
    })
  }
  return result
}
