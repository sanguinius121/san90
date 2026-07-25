import { useEffect, useRef, useState } from 'react'
import { analyzerApi, type FrequencyScanApi } from '../data/controlApi'
import {
  DEFAULT_SCAN_DURATION_SECONDS,
  DEFAULT_FREQUENCY_SCAN_ENTRIES,
  MIN_SCAN_DURATION_SECONDS,
  SCAN_DURATION_STEP_SECONDS,
  formatScanNumber,
  frequencyDraftFromHz,
  validateFrequencyScanDrafts,
  type FrequencyScanDraftEntry,
} from '../data/frequencyScan'
import {
  CENTER_FREQUENCY_UNITS,
  displayValueToHz,
  type CenterFrequencyUnit,
} from '../data/frequencyUnits'
import { useDeviceStore, useRuntimeStore } from '../stores'

let nextScanEntryId=0

function createEntry(
  frequencyHz:number,
  frequencyUnit:CenterFrequencyUnit='GHz',
):FrequencyScanDraftEntry {
  return {
    id:`frequency-scan-${++nextScanEntryId}`,
    enabled:true,
    frequencyHz,
    frequencyUnit,
    frequencyDraft:frequencyDraftFromHz(frequencyHz,frequencyUnit),
    durationSeconds:DEFAULT_SCAN_DURATION_SECONDS,
    durationDraft:String(DEFAULT_SCAN_DURATION_SECONDS),
  }
}

interface FrequencyScanControlProps {
  minimumFrequencyHz:number
  maximumFrequencyHz:number
  disabled?:boolean
}

export function FrequencyScanControl({
  minimumFrequencyHz,
  maximumFrequencyHz,
  disabled=false,
}:FrequencyScanControlProps) {
  const currentCenterHz=useDeviceStore((state)=>state.centerHz)
  const scan=useRuntimeStore((state)=>state.frequencyScan)
  const analyzerReconfiguring=useRuntimeStore((state)=>state.reconfiguring)
  const [entries,setEntries]=useState<FrequencyScanDraftEntry[]>(()=>
    DEFAULT_FREQUENCY_SCAN_ENTRIES.map(entry=>
      createEntry(entry.frequencyHz,entry.frequencyUnit),
    ),
  )
  const [requestPending,setRequestPending]=useState(false)
  const [error,setError]=useState<string|null>(null)
  const draftsTouched=useRef(false)
  const locked=disabled||requestPending||scan.running||analyzerReconfiguring

  useEffect(()=>{
    let active=true
    void analyzerApi.frequencyScanStatus().then(status=>{
      if(!active||draftsTouched.current||!status.entries.length)return
      setEntries(status.entries.map(entry=>({
        id:entry.id,
        enabled:entry.enabled,
        frequencyHz:entry.center_frequency_hz,
        frequencyUnit:'GHz',
        frequencyDraft:frequencyDraftFromHz(entry.center_frequency_hz,'GHz'),
        durationSeconds:entry.duration_seconds,
        durationDraft:formatScanNumber(entry.duration_seconds,3),
      })))
    }).catch(()=>{/* Frequency scan may be unavailable on an older backend. */})
    return()=>{active=false}
  },[])

  const update=(id:string,changes:Partial<FrequencyScanDraftEntry>)=>{
    draftsTouched.current=true
    setEntries(current=>current.map(entry=>entry.id===id?{...entry,...changes}:entry))
  }
  const commitFrequency=(entry:FrequencyScanDraftEntry)=>{
    const displayValue=Number(entry.frequencyDraft)
    const frequencyHz=displayValueToHz(displayValue,entry.frequencyUnit)
    if(!entry.frequencyDraft.trim()||!Number.isFinite(frequencyHz)||frequencyHz<=0||frequencyHz<minimumFrequencyHz||frequencyHz>maximumFrequencyHz){
      setError('Each scan frequency must be within the analyzer frequency range.')
      return
    }
    update(entry.id,{frequencyHz,frequencyDraft:frequencyDraftFromHz(frequencyHz,entry.frequencyUnit)})
    setError(null)
  }
  const changeUnit=(entry:FrequencyScanDraftEntry,nextUnit:CenterFrequencyUnit)=>{
    const parsed=Number(entry.frequencyDraft)
    const sourceHz=entry.frequencyDraft.trim()&&Number.isFinite(parsed)
      ?displayValueToHz(parsed,entry.frequencyUnit)
      :entry.frequencyHz
    update(entry.id,{
      frequencyUnit:nextUnit,
      frequencyDraft:frequencyDraftFromHz(sourceHz,nextUnit),
    })
  }
  const commitDuration=(entry:FrequencyScanDraftEntry)=>{
    const duration=Number(entry.durationDraft)
    if(!entry.durationDraft.trim()||!Number.isFinite(duration)||duration<MIN_SCAN_DURATION_SECONDS){
      setError(`Dwell duration must be at least ${MIN_SCAN_DURATION_SECONDS} seconds.`)
      return
    }
    update(entry.id,{durationSeconds:duration,durationDraft:formatScanNumber(duration,3)})
    setError(null)
  }
  const applyStatus=(status:FrequencyScanApi)=>{
    useRuntimeStore.getState().update({frequencyScan:{
      running:status.running,
      state:status.state,
      active_entry_id:status.active_entry_id,
      active_index:status.active_index,
      active_count:status.active_count,
      verified_center_frequency_hz:status.verified_center_frequency_hz,
      dwell_duration_seconds:status.dwell_duration_seconds,
      remaining_dwell_seconds:status.remaining_dwell_seconds,
      last_error:status.last_error,
    }})
  }
  const start=async()=>{
    const config=validateFrequencyScanDrafts(entries,minimumFrequencyHz,maximumFrequencyHz)
    if(!config||!config.length||!config.some(entry=>entry.enabled)){
      setError('Enable at least one valid frequency and enter valid dwell durations.')
      return
    }
    setRequestPending(true)
    setError(null)
    try{
      setEntries(current=>current.map(entry=>{
        const configured=config.find(candidate=>candidate.id===entry.id)
        return configured?{
          ...entry,
          frequencyHz:configured.center_frequency_hz,
          durationSeconds:configured.duration_seconds,
        }:entry
      }))
      await analyzerApi.configureFrequencyScan(config)
      applyStatus(await analyzerApi.startFrequencyScan())
    }catch(requestError){
      setError(requestError instanceof Error?requestError.message:'Unable to start frequency scan')
    }finally{
      setRequestPending(false)
    }
  }
  const stop=async()=>{
    setRequestPending(true)
    setError(null)
    try{
      applyStatus(await analyzerApi.stopFrequencyScan())
    }catch(requestError){
      setError(requestError instanceof Error?requestError.message:'Unable to stop frequency scan')
    }finally{
      setRequestPending(false)
    }
  }
  const activeEntry=entries.find(entry=>entry.id===scan.active_entry_id)
  const verifiedUnit=activeEntry?.frequencyUnit??'GHz'
  return <div className="frequency-scan-control">
    {(scan.running||scan.state==='error')&&<div className={`frequency-scan-status ${scan.state==='error'?'is-error':''}`} title={scan.last_error??undefined}>
      <b>{scan.running&&scan.active_index!=null?`Scanning ${scan.active_index}/${scan.active_count}`:scan.state.toUpperCase()}</b>
      {scan.verified_center_frequency_hz!=null&&<span>{frequencyDraftFromHz(scan.verified_center_frequency_hz,verifiedUnit)} {verifiedUnit}</span>}
      {scan.remaining_dwell_seconds!=null&&<span>{scan.remaining_dwell_seconds.toFixed(1)} s</span>}
      {scan.state==='error'&&scan.last_error&&<span>{scan.last_error}</span>}
    </div>}
    {entries.map((entry,index)=><div key={entry.id} className={`frequency-scan-entry ${scan.active_entry_id===entry.id?'is-active':''}`}>
      <div className="frequency-scan-entry__heading">
        <label><input type="checkbox" aria-label={`Scan ${index+1} enabled`} checked={entry.enabled} disabled={locked} onChange={event=>update(entry.id,{enabled:event.target.checked})}/><span>#{index+1}</span></label>
        <button aria-label={`Delete scan ${index+1}`} disabled={locked} onClick={()=>{draftsTouched.current=true;setEntries(current=>current.filter(candidate=>candidate.id!==entry.id))}}>DELETE</button>
      </div>
      <div className="frequency-scan-entry__fields">
        <div className="frequency-scan-frequency">
          <input type="number" step="any" min="0" aria-label={`Scan ${index+1} center frequency`} inputMode="decimal" disabled={locked} value={entry.frequencyDraft} onChange={event=>update(entry.id,{frequencyDraft:event.target.value})} onBlur={()=>commitFrequency(entry)} onKeyDown={event=>{if(event.key==='Enter')commitFrequency(entry)}}/>
          <select aria-label={`Scan ${index+1} frequency unit`} disabled={locked} value={entry.frequencyUnit} onChange={event=>changeUnit(entry,event.target.value as CenterFrequencyUnit)}>
            {CENTER_FREQUENCY_UNITS.map(unit=><option key={unit} value={unit}>{unit}</option>)}
          </select>
        </div>
        <div className="frequency-scan-duration">
          <input type="number" min={MIN_SCAN_DURATION_SECONDS} step={SCAN_DURATION_STEP_SECONDS} aria-label={`Scan ${index+1} duration`} inputMode="decimal" disabled={locked} value={entry.durationDraft} onChange={event=>update(entry.id,{durationDraft:event.target.value})} onBlur={()=>commitDuration(entry)} onKeyDown={event=>{if(event.key==='Enter')commitDuration(entry)}}/>
          <em>s</em>
        </div>
      </div>
    </div>)}
    {error&&<div className="frequency-scan-error" role="alert">{error}</div>}
    <div className="frequency-scan-actions">
      <button disabled={locked} onClick={()=>{draftsTouched.current=true;setEntries(current=>{let added=createEntry(currentCenterHz);while(current.some(entry=>entry.id===added.id))added=createEntry(currentCenterHz);return[...current,added]})}}>+ Add frequency</button>
      <button disabled={locked} onClick={()=>void start()}>Start scan</button>
      <button disabled={disabled||requestPending||!scan.running} onClick={()=>void stop()}>Stop scan</button>
    </div>
    <span className="frequency-scan-constraints">Dwell ≥ {MIN_SCAN_DURATION_SECONDS}s · step {SCAN_DURATION_STEP_SECONDS}s</span>
  </div>
}
