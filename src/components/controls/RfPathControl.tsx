import { useEffect, useMemo, useState } from 'react'
import { rfSwitchApi, type RfPathId, type RfSwitchCapabilitiesApi } from '../../data/controlApi'
import { useRfSwitchStore } from '../../stores'
import { SelectControl } from './SelectControl'
import { useRfSidebarLocalization } from '../../data/rfSidebarLocalization'

const fallbackPaths = Array.from({length:8},(_,index)=>({
  id:`rf${index+1}` as RfPathId,
  rf_channel:`RF${index+1}`,
  address:index,
  label:index===0?'RF1 — 2.4/5.8 GHz LNA':index===7?'RF8 — Wideband antenna':`RF${index+1} — Auxiliary`,
  external_lna:index===0,
}))

const fallbackCapabilities:RfSwitchCapabilitiesApi={
  enabled:false,default_path:'rf8',selection_policy:'session-only-manual',paths:fallbackPaths,
}

export function RfPathControl(){
  const text=useRfSidebarLocalization('RF Path')
  const state=useRfSwitchStore()
  const [capabilities,setCapabilities]=useState(fallbackCapabilities)

  useEffect(()=>{
    let active=true
    const refresh=async()=>{
      try{
        const [caps,status]=await Promise.all([rfSwitchApi.capabilities(),rfSwitchApi.status()])
        if(!active)return
        setCapabilities(caps)
        useRfSwitchStore.getState().update({...status,loading:false})
      }catch(error){
        if(active)useRfSwitchStore.getState().update({connection_state:'error',hardware_present:false,available:false,connected:false,requested_path:null,reported_path:null,expected_fail_safe_path:null,verification:'unavailable',readback_matches_request:false,loading:false,last_error:error instanceof Error?error.message:'RF switch status unavailable'})
      }
    }
    void refresh()
    const timer=window.setInterval(()=>void refresh(),2000)
    return()=>{active=false;window.clearInterval(timer)}
  },[])

  const options=useMemo(()=>capabilities.paths.map(path=>{
    const source=/^RF[2-7] — Auxiliary$/u.test(path.label)?'RF2…RF7 — Auxiliary':path.label
    const localized=text.t(source)
    return {value:path.id,label:source==='RF2…RF7 — Auxiliary'?localized.replace('RF2…RF7',path.rf_channel):localized}
  }),[capabilities.paths,text])
  const selected=state.reported_path??state.requested_path??'rf8'
  const commit=async(path:string)=>{
    const requested=path as RfPathId
    state.update({applying:true,last_error:null})
    try{
      state.update({...await rfSwitchApi.setPath(requested),applying:false})
    }catch(error){
      try{state.update({...await rfSwitchApi.status(),applying:false})}
      catch{state.update({applying:false})}
      state.update({last_error:error instanceof Error?error.message:'RF path change failed'})
    }
  }
  const verifiedLna=state.reported_path==='rf1'&&state.readback_matches_request
  const mismatch=state.verification==='mismatch'
  const unavailableMessage=!state.hardware_present
    ?text.t('The FT232H and externally powered RF switch are disconnected. RF path is unknown.')
    :state.expected_fail_safe_path==='rf8'
      ?text.t('FT232H communication is unavailable. RF8 is the expected pull-up fail-safe path, but it is not verified.')
      :null
  const connectionLabel=state.simulated&&state.connection_state==='available'?text.t('SIMULATED'):state.connection_state==='available'?text.t('FT232H CONNECTED'):state.connection_state==='reconnecting'?text.t('RECONNECTING · {attempts}',{attempts:state.reconnect_attempts}):text.t(state.connection_state.toUpperCase())
  return <div className="rf-path-control">
    <SelectControl label={text.t('RF input path')} title={text.hint('RF input path')} value={selected} options={options} disabled={state.loading||state.applying||!capabilities.enabled||state.connection_state!=='available'||state.verification!=='verified'} onChange={(value)=>void commit(value)}/>
    <div className="rf-path-status" aria-live="polite">
      <span title={text.hint('Requested')}><i>{text.t('Requested')}</i><b>{state.requested_path?.toUpperCase()??text.t('UNKNOWN')}</b></span>
      <span title={text.hint('Hardware')}><i>{text.t('Hardware')}</i><b>{state.reported_path?.toUpperCase()??text.t('UNKNOWN')}</b></span>
      <span title={text.hint('GPIO')}><i>{text.t('GPIO')}</i><b>{state.raw_address==null?'---':state.raw_address.toString(2).padStart(3,'0')}</b></span>
      <span className={state.connection_state==='available'?'is-connected':'is-unavailable'}>{connectionLabel}</span>
    </div>
    {verifiedLna&&<><div className="rf-lna-badge">{text.t('EXTERNAL LNA ACTIVE')}</div><p className="rf-path-note">{text.t('External 2.4/5.8 GHz LNA path selected. Monitor receiver overload when strong nearby signals are present.')}</p></>}
    {mismatch&&<div className="rf-path-warning" role="alert">{text.t('Requested path is not verified by GPIO readback.')}</div>}
    {unavailableMessage&&state.connection_state!=='disabled'&&<div className="rf-path-warning">{unavailableMessage}</div>}
    {state.last_error&&<div className="rf-path-warning">{text.t(state.last_error)}</div>}
  </div>
}
