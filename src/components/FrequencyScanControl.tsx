import { useEffect, useRef, useState } from 'react'
import { analyzerApi, type FrequencyScanApi, type FrequencyScanEntryApi } from '../data/controlApi'
import {
  DEFAULT_SCAN_DURATION_MS,
  DEFAULT_FREQUENCY_SCAN_ENTRIES,
  DEFAULT_SCAN_STEP_HZ,
  MIN_SCAN_DURATION_MS,
  SCAN_DURATION_STEP_MS,
  formatScanNumber,
  frequencyDraftFromHz,
  scanEntryApiFromDraft,
  validateFrequencyScanDrafts,
  type FrequencyScanDraftEntry,
} from '../data/frequencyScan'
import {
  CENTER_FREQUENCY_UNITS,
  displayValueToHz,
  type CenterFrequencyUnit,
} from '../data/frequencyUnits'
import { useDeviceStore, useRuntimeStore } from '../stores'
import { useRfSidebarLocalization } from '../data/rfSidebarLocalization'

let nextScanEntryId=0

function createEntry(
  frequencyHz:number,
  frequencyUnit:CenterFrequencyUnit='GHz',
):FrequencyScanDraftEntry {
  return {
    id:`frequency-scan-${Date.now()}-${++nextScanEntryId}`,
    enabled:true,
    frequencyHz,
    frequencyUnit,
    frequencyDraft:frequencyDraftFromHz(frequencyHz,frequencyUnit),
    stepHz:DEFAULT_SCAN_STEP_HZ,
    stepUnit:'MHz',
    stepDraft:'10',
    durationMs:DEFAULT_SCAN_DURATION_MS,
    durationDraft:formatScanNumber(DEFAULT_SCAN_DURATION_MS/1000,3),
  }
}

function draftFromApi(entry:FrequencyScanEntryApi):FrequencyScanDraftEntry {
  const legacy=entry as FrequencyScanEntryApi&{
    duration_seconds?:number
    display_unit?:CenterFrequencyUnit
    step_hz?:number
    step_unit?:CenterFrequencyUnit
  }
  const frequencyUnit=legacy.display_unit??'GHz'
  const stepHz=legacy.step_hz??DEFAULT_SCAN_STEP_HZ
  const stepUnit=legacy.step_unit??'MHz'
  const durationMs=Number.isFinite(legacy.duration_ms)
    ?legacy.duration_ms
    :(legacy.duration_seconds??DEFAULT_SCAN_DURATION_MS/1000)*1000
  return {
    id:entry.id,
    enabled:entry.enabled,
    frequencyHz:entry.center_frequency_hz,
    frequencyUnit,
    frequencyDraft:frequencyDraftFromHz(entry.center_frequency_hz,frequencyUnit),
    stepHz,
    stepUnit,
    stepDraft:frequencyDraftFromHz(stepHz,stepUnit),
    durationMs,
    durationDraft:formatScanNumber(durationMs/1000,3),
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
  const text=useRfSidebarLocalization('Frequency Scan')
  const currentCenterHz=useDeviceStore((state)=>state.centerHz)
  const scan=useRuntimeStore((state)=>state.frequencyScan)
  const [entries,setEntries]=useState<FrequencyScanDraftEntry[]>(()=>
    DEFAULT_FREQUENCY_SCAN_ENTRIES.map(entry=>createEntry(entry.frequencyHz,entry.frequencyUnit)),
  )
  const entriesRef=useRef(entries)
  const [requestPending,setRequestPending]=useState(false)
  const [error,setError]=useState<string|null>(null)
  const draftsTouched=useRef(false)
  const saveSequence=useRef(0)
  const entryControlsDisabled=disabled||requestPending

  const setLocalEntries=(next:FrequencyScanDraftEntry[])=>{
    entriesRef.current=next
    setEntries(next)
  }
  const replaceEntry=(id:string,changes:Partial<FrequencyScanDraftEntry>)=>{
    draftsTouched.current=true
    const next=entriesRef.current.map(entry=>entry.id===id?{...entry,...changes}:entry)
    setLocalEntries(next)
    return next
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
  const persistEntries=async(next:FrequencyScanDraftEntry[]):Promise<boolean>=>{
    const config=validateFrequencyScanDrafts(next,minimumFrequencyHz,maximumFrequencyHz)
    if(!config){
      setError(text.t('Enter valid frequencies, positive steps, and dwell durations.'))
      return false
    }
    const sequence=++saveSequence.current
    try{
      const status=await analyzerApi.configureFrequencyScan(config)
      if(sequence===saveSequence.current){
        applyStatus(status)
        setError(status.configuration_save_error)
      }
      return !status.configuration_save_error
    }catch(requestError){
      if(sequence===saveSequence.current){
        setError(requestError instanceof Error?requestError.message:text.t('Unable to save frequency scan'))
      }
      return false
    }
  }
  const normalizedChanges=(validated:FrequencyScanEntryApi):Partial<FrequencyScanDraftEntry>=>({
    frequencyHz:validated.center_frequency_hz,
    frequencyDraft:frequencyDraftFromHz(validated.center_frequency_hz,validated.display_unit),
    stepHz:validated.step_hz,
    stepDraft:frequencyDraftFromHz(validated.step_hz,validated.step_unit),
    durationMs:validated.duration_ms,
    durationDraft:formatScanNumber(validated.duration_ms/1000,3),
  })
  const commitEntry=(entry:FrequencyScanDraftEntry)=>{
    const validated=scanEntryApiFromDraft(entry,minimumFrequencyHz,maximumFrequencyHz)
    if(!validated){
      setError(text.t('Frequency, step, or duration is outside the supported range.'))
      return
    }
    const next=replaceEntry(entry.id,normalizedChanges(validated))
    setError(null)
    void persistEntries(next)
  }
  const changeUnit=(entry:FrequencyScanDraftEntry,nextUnit:CenterFrequencyUnit)=>{
    const parsed=Number(entry.frequencyDraft)
    const sourceHz=entry.frequencyDraft.trim()&&Number.isFinite(parsed)
      ?displayValueToHz(parsed,entry.frequencyUnit)
      :entry.frequencyHz
    if(!Number.isFinite(sourceHz)||sourceHz<minimumFrequencyHz||sourceHz>maximumFrequencyHz){
      setError(text.t('Each scan frequency must be within the analyzer frequency range.'))
      return
    }
    const next=replaceEntry(entry.id,{
      frequencyHz:sourceHz,
      frequencyUnit:nextUnit,
      frequencyDraft:frequencyDraftFromHz(sourceHz,nextUnit),
    })
    setError(null)
    void persistEntries(next)
  }
  const changeStepUnit=(entry:FrequencyScanDraftEntry,nextUnit:CenterFrequencyUnit)=>{
    const parsed=Number(entry.stepDraft)
    const sourceHz=entry.stepDraft.trim()&&Number.isFinite(parsed)
      ?displayValueToHz(parsed,entry.stepUnit)
      :entry.stepHz
    if(!Number.isFinite(sourceHz)||sourceHz<=0||sourceHz>maximumFrequencyHz-minimumFrequencyHz){
      setError(text.t('Step must be positive and no larger than the supported tuning range.'))
      return
    }
    const next=replaceEntry(entry.id,{
      stepHz:sourceHz,
      stepUnit:nextUnit,
      stepDraft:frequencyDraftFromHz(sourceHz,nextUnit),
    })
    setError(null)
    void persistEntries(next)
  }
  const adjustFrequency=(entry:FrequencyScanDraftEntry,direction:-1|1)=>{
    const validated=scanEntryApiFromDraft(entry,minimumFrequencyHz,maximumFrequencyHz)
    if(!validated){
      setError(text.t('Enter a valid frequency, step, and duration before applying the step.'))
      return
    }
    const frequencyHz=validated.center_frequency_hz+direction*validated.step_hz
    if(frequencyHz<minimumFrequencyHz||frequencyHz>maximumFrequencyHz){
      setError(text.t('The requested step would exceed the analyzer frequency range.'))
      return
    }
    const next=replaceEntry(entry.id,{
      ...normalizedChanges(validated),
      frequencyHz,
      frequencyDraft:frequencyDraftFromHz(frequencyHz,entry.frequencyUnit),
    })
    setError(null)
    void persistEntries(next)
  }

  useEffect(()=>{
    let active=true
    void analyzerApi.frequencyScanStatus().then(status=>{
      if(!active||draftsTouched.current)return
      setLocalEntries(status.entries.map(draftFromApi))
      if(status.configuration_save_error)setError(status.configuration_save_error)
      else if(status.configuration_load_warning)setError(status.configuration_load_warning)
    }).catch(()=>{/* Frequency scan may be unavailable on an older backend. */})
    return()=>{active=false}
  },[])

  const start=async()=>{
    const config=validateFrequencyScanDrafts(entriesRef.current,minimumFrequencyHz,maximumFrequencyHz)
    if(!config||!config.length||!config.some(entry=>entry.enabled)){
      setError(text.t('Enable at least one valid frequency and enter valid steps and dwell durations.'))
      return
    }
    setRequestPending(true)
    setError(null)
    try{
      const configured=await analyzerApi.configureFrequencyScan(config)
      if(configured.configuration_save_error)throw new Error(configured.configuration_save_error)
      applyStatus(await analyzerApi.startFrequencyScan())
    }catch(requestError){
      setError(requestError instanceof Error?requestError.message:text.t('Unable to start frequency scan'))
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
      setError(requestError instanceof Error?requestError.message:text.t('Unable to stop frequency scan'))
    }finally{
      setRequestPending(false)
    }
  }
  const activeEntry=entries.find(entry=>entry.id===scan.active_entry_id)
  const verifiedUnit=activeEntry?.frequencyUnit??'GHz'
  return <div className="frequency-scan-control">
    {(scan.running||scan.state==='error')&&<div className={`frequency-scan-status ${scan.state==='error'?'is-error':''}`} title={scan.last_error??undefined}>
      <b>{scan.running&&scan.active_index!=null?text.t('Scanning {current}/{total}',{current:scan.active_index,total:scan.active_count}):text.t(scan.state.toUpperCase())}</b>
      {scan.verified_center_frequency_hz!=null&&<span>{frequencyDraftFromHz(scan.verified_center_frequency_hz,verifiedUnit)} {verifiedUnit}</span>}
      {scan.remaining_dwell_seconds!=null&&<span>{scan.remaining_dwell_seconds.toFixed(1)} s</span>}
      {scan.state==='error'&&scan.last_error&&<span>{scan.last_error}</span>}
    </div>}
    {entries.map((entry,index)=>{
      const decrementDisabled=entry.frequencyHz-entry.stepHz<minimumFrequencyHz
      const incrementDisabled=entry.frequencyHz+entry.stepHz>maximumFrequencyHz
      return <div key={entry.id} className={`frequency-scan-entry ${scan.active_entry_id===entry.id?'is-active':''}`}>
        <div className="frequency-scan-entry__heading">
          <label title={text.hint('Scan {index} enabled',{index:index+1})}><input type="checkbox" aria-label={text.t('Scan {index} enabled',{index:index+1})} checked={entry.enabled} disabled={entryControlsDisabled} onChange={event=>{
            const next=replaceEntry(entry.id,{enabled:event.target.checked})
            void persistEntries(next)
          }}/><span>#{index+1}</span></label>
          <button aria-label={text.t('Delete scan {index}',{index:index+1})} title={text.hint('Delete scan {index}',{index:index+1})} disabled={entryControlsDisabled} onClick={()=>{
            draftsTouched.current=true
            const next=entriesRef.current.filter(candidate=>candidate.id!==entry.id)
            setLocalEntries(next)
            void persistEntries(next)
          }}>{text.t('DELETE')}</button>
        </div>
        <div className="frequency-scan-entry__frequency-row">
          <div className="frequency-scan-frequency">
            <input type="number" step="any" min="0" aria-label={text.t('Scan {index} center frequency',{index:index+1})} inputMode="decimal" disabled={entryControlsDisabled} value={entry.frequencyDraft} onChange={event=>replaceEntry(entry.id,{frequencyDraft:event.target.value})} onBlur={()=>commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)} onKeyDown={event=>{if(event.key==='Enter')commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)}}/>
            <select aria-label={text.t('Scan {index} frequency unit',{index:index+1})} disabled={entryControlsDisabled} value={entry.frequencyUnit} onChange={event=>changeUnit(entry,event.target.value as CenterFrequencyUnit)}>
              {CENTER_FREQUENCY_UNITS.map(unit=><option key={unit} value={unit}>{unit}</option>)}
            </select>
          </div>
          <button className="frequency-scan-step-button" aria-label={text.t('Decrease scan {index} frequency',{index:index+1})} title={text.hint('Decrease scan {index} frequency',{index:index+1})} disabled={entryControlsDisabled||decrementDisabled} onClick={()=>adjustFrequency(entry,-1)}>−</button>
          <button className="frequency-scan-step-button" aria-label={text.t('Increase scan {index} frequency',{index:index+1})} title={text.hint('Increase scan {index} frequency',{index:index+1})} disabled={entryControlsDisabled||incrementDisabled} onClick={()=>adjustFrequency(entry,1)}>+</button>
        </div>
        <div className="frequency-scan-entry__detail-row">
          <label title={text.hint('Step')}>{text.t('Step')}</label>
          <div className="frequency-scan-step">
            <input type="number" step="any" min="0" aria-label={text.t('Scan {index} step',{index:index+1})} inputMode="decimal" disabled={entryControlsDisabled} value={entry.stepDraft} onChange={event=>replaceEntry(entry.id,{stepDraft:event.target.value})} onBlur={()=>commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)} onKeyDown={event=>{if(event.key==='Enter')commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)}}/>
            <select aria-label={text.t('Scan {index} step unit',{index:index+1})} disabled={entryControlsDisabled} value={entry.stepUnit} onChange={event=>changeStepUnit(entry,event.target.value as CenterFrequencyUnit)}>
              {CENTER_FREQUENCY_UNITS.map(unit=><option key={unit} value={unit}>{unit}</option>)}
            </select>
          </div>
          <label title={text.hint('Duration')}>{text.t('Duration')}</label>
          <div className="frequency-scan-duration">
            <input type="number" min={MIN_SCAN_DURATION_MS/1000} step={SCAN_DURATION_STEP_MS/1000} aria-label={text.t('Scan {index} duration',{index:index+1})} inputMode="decimal" disabled={entryControlsDisabled} value={entry.durationDraft} onChange={event=>replaceEntry(entry.id,{durationDraft:event.target.value})} onBlur={()=>commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)} onKeyDown={event=>{if(event.key==='Enter')commitEntry(entriesRef.current.find(candidate=>candidate.id===entry.id)??entry)}}/>
            <em>s</em>
          </div>
        </div>
      </div>
    })}
    {error&&<div className="frequency-scan-error" role="alert">{error}</div>}
    <div className="frequency-scan-actions">
      <button disabled={entryControlsDisabled} onClick={()=>{
        draftsTouched.current=true
        let added=createEntry(currentCenterHz)
        while(entriesRef.current.some(entry=>entry.id===added.id))added=createEntry(currentCenterHz)
        const next=[...entriesRef.current,added]
        setLocalEntries(next)
        void persistEntries(next)
      }}>{text.t('+ Add frequency')}</button>
      <button disabled={disabled||requestPending||scan.running} onClick={()=>void start()}>{text.t('Start scan')}</button>
      <button disabled={disabled||requestPending||!scan.running} onClick={()=>void stop()}>{text.t('Stop scan')}</button>
    </div>
    <span className="frequency-scan-constraints">{text.t('Dwell ≥ {seconds}s · default step 10 MHz',{seconds:MIN_SCAN_DURATION_MS/1000})}</span>
  </div>
}
