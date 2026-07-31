import { useCallback, useEffect, useRef, useState } from 'react'
import { ControlSection } from './controls/ControlSection'
import { NumericControl } from './controls/NumericControl'
import { SelectControl } from './controls/SelectControl'
import { ToggleControl } from './controls/ToggleControl'
import { useDeviceStore, useRuntimeStore } from '../stores'
import { analyzerApi, type AnalyzerCapabilitiesApi, type AnalyzerSettingsApi } from '../data/controlApi'
import { ResolutionTradeoffControl } from './controls/ResolutionTradeoffControl'
import canonicalSteps from '../../config/san90-resolution-tradeoff.json'
import type { ResolutionTradeoffStepApi } from '../data/controlApi'
import { RfPathControl } from './controls/RfPathControl'
import {
  CENTER_FREQUENCY_UNITS,
  centerFrequencyPrecision,
  displayValueToHz,
  hzToDisplayValue,
  type CenterFrequencyUnit,
} from '../data/frequencyUnits'
import { FrequencyScanControl } from './FrequencyScanControl'
import {
  bandwidthPrecision,
  compactBandwidthUnit,
  hzToBandwidthDisplay,
} from '../data/bandwidthUnits'
import { RecordControl } from './controls/RecordControl'
import { PlaybackControl } from './controls/PlaybackControl'
import {
  applyAnalyzerState,
  commitCenterFrequencyHz,
} from '../data/centerFrequencyControl'

const options = (values: [string,string][]) => values.map(([label,value])=>({label,value}))
export const REFERENCE_LEVEL_STEP_DB = 10
export const AMPLITUDE_OFFSET_MIN_DB = -100
export const AMPLITUDE_OFFSET_MAX_DB = 100
export const AMPLITUDE_OFFSET_STEP_DB = 1
const SAN90_ATTENUATION_STEP_DB = 3
const IF_AGC_TARGET_MIN_DBFS=-30
const IF_AGC_TARGET_MAX_DBFS=0
const IF_AGC_PERIOD_MIN_S=-1
const IF_AGC_PERIOD_MAX_S=2_147_483
const labels:Record<string,string>={auto:'Auto',manual:'Manual',off:'Off',low:'Low gain',medium:'Medium gain',high:'High gain','low-noise':'Low noise','high-linearity':'High linearity','flat-top':'Flat top','blackman-nuttall':'Blackman–Nuttall','low-sidelobe':'Low sidelobe',rectangular:'Rectangular',kaiser:'Kaiser',sample:'Sample','positive-peak':'Positive peak',average:'Average','negative-peak':'Negative peak',rms:'RMS','auto-peak':'Auto peak'}
const localSteps=canonicalSteps as ResolutionTradeoffStepApi[]
const localCapabilities:AnalyzerCapabilitiesApi={source:'simulator',supported_controls:['center_frequency_hz','reference_level_dbm','attenuation_db','preamplifier','gain_strategy','amplitude_offset_db','if_agc_enabled','if_agc_target_dbfs','if_agc_period_s','rbw_hz','rbw_mode','resolution_tradeoff_index','window','detector'],numeric_ranges:{amplitude_offset_db:{minimum:AMPLITUDE_OFFSET_MIN_DB,maximum:AMPLITUDE_OFFSET_MAX_DB,step:AMPLITUDE_OFFSET_STEP_DB},if_agc_target_dbfs:{minimum:IF_AGC_TARGET_MIN_DBFS,maximum:IF_AGC_TARGET_MAX_DBFS,step:1},if_agc_period_s:{minimum:IF_AGC_PERIOD_MIN_S,maximum:IF_AGC_PERIOD_MAX_S,step:1}},enum_values:{},center_frequency_min_hz:1e6,center_frequency_max_hz:9.5e9,center_frequency_step_hz:1,reference_level_min_dbm:-80,reference_level_max_dbm:20,supported_attenuation_values_db:null,supports_automatic_attenuation:true,preamplifier_modes:['auto','off','low','medium','high'],gain_strategy_modes:['low-noise','high-linearity'],requires_restart_for_frequency:false,requires_restart_for_amplitude:false,supports_rbw_control:true,rbw_control_mode:'auto-or-manual-numeric',supported_rbw_values_hz:localSteps.map(step=>step.actual_rbw_hz),rbw_min_hz:100,rbw_max_hz:1e7,rbw_is_discrete:false,rbw_is_profile_based:false,rbw_changes_point_count:true,rbw_changes_span:false,rbw_requires_restart:false,window_modes:['flat-top','blackman-nuttall','low-sidelobe','rectangular','kaiser'],detector_modes:['sample','positive-peak','average','negative-peak','rms','auto-peak'],window_requires_restart:false,detector_requires_restart:false,supports_resolution_tradeoff:true,resolution_tradeoff_steps:localSteps,resolution_tradeoff_min_index:0,resolution_tradeoff_max_index:7,resolution_tradeoff_direction:{left:'time',right:'frequency'},default_resolution_tradeoff_index:5,supports_auto_rbw:true}

export function ControlSidebar({defaultSectionsOpen=false,onResetLayout}:{defaultSectionsOpen?:boolean;onResetLayout?:()=>void}={}) {
  const d=useDeviceStore(); const set=d.set; const runtime=useRuntimeStore(); const hardware=runtime.source==='san90'
  const [capabilities,setCapabilities]=useState<AnalyzerCapabilitiesApi>(localCapabilities); const [loading,setLoading]=useState(hardware); const [controlRevision,setControlRevision]=useState(0); const [centerUnit,setCenterUnit]=useState<CenterFrequencyUnit>('GHz')
  const activeVbwUnit=compactBandwidthUnit(d.vbwHz)
  const vbwReadback=Number.isFinite(d.vbwHz)&&d.vbwHz>0
    ?String(Number(hzToBandwidthDisplay(d.vbwHz,activeVbwUnit).toFixed(bandwidthPrecision(activeVbwUnit))))
    :'—'
  const periodicSeconds=useRef(1)
  const supported=(name:string)=>capabilities.supported_controls.includes(name)
  const applyState=useCallback((state:AnalyzerSettingsApi)=>{applyAnalyzerState(state);setControlRevision(revision=>revision+1)},[])
  useEffect(()=>{let active=true;if(!hardware)return
    Promise.all([analyzerApi.capabilities(),analyzerApi.settings()]).then(([caps,state])=>{if(active){setCapabilities(caps);applyState(state);useRuntimeStore.getState().update({lastError:undefined})}}).catch(error=>{if(active)useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'Unable to load analyzer controls'})}).finally(()=>{if(active)setLoading(false)});return()=>{active=false}
  },[hardware,applyState])
  useEffect(()=>{
    if(d.ifAgcPeriodS>0)periodicSeconds.current=d.ifAgcPeriodS
  },[d.ifAgcPeriodS])
  useEffect(()=>{
    if(!hardware||loading)return
    let active=true
    const poll=()=>{void analyzerApi.settings().then(state=>{
      if(!active)return
      const actual=state.actual
      const current=useDeviceStore.getState()
      useDeviceStore.setState({
        ifAgc:actual.if_agc_enabled??current.ifAgc,
        ifAgcTargetDbfs:actual.if_agc_target_dbfs??current.ifAgcTargetDbfs,
        ifAgcPeriodS:actual.if_agc_period_s??current.ifAgcPeriodS,
        ifAgcGainDb:actual.if_agc_gain_db===undefined?current.ifAgcGainDb:actual.if_agc_gain_db,
        vbwMode:actual.vbw_mode??current.vbwMode,
        vbwHz:actual.vbw_hz??current.vbwHz,
      })
    }).catch(()=>{/* The normal connection/status path reports analyzer loss. */})}
    const timer=window.setInterval(poll,500)
    poll()
    return()=>{active=false;window.clearInterval(timer)}
  },[hardware,loading])
  const commit=async(path:string,body:object,local:()=>void)=>{if(!hardware){local();return}useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{const response=await analyzerApi.put<AnalyzerSettingsApi|{settings:AnalyzerSettingsApi}>(path,body);applyState('settings'in response?response.settings:response)}catch(error){useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'Configuration failed'});try{applyState(await analyzerApi.settings())}catch{ /* retain the original control error */ }}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const centerMinimumHz=capabilities.center_frequency_min_hz??1
  const centerMaximumHz=capabilities.center_frequency_max_hz??Number.MAX_SAFE_INTEGER
  const validCenterDisplayValue=(value:number)=>{const hz=displayValueToHz(value,centerUnit);return Number.isFinite(hz)&&hz>0&&hz>=centerMinimumHz&&hz<=centerMaximumHz}
  const rejectCenterFrequency=()=>useRuntimeStore.getState().update({lastError:`Center frequency must be between ${centerMinimumHz} Hz and ${centerMaximumHz} Hz`})
  const commitCenterFrequency=async(value:number):Promise<number|false>=>{
    const result=await commitCenterFrequencyHz(displayValueToHz(value,centerUnit),{
      minimumHz:centerMinimumHz,
      maximumHz:centerMaximumHz,
    })
    if(!result)return false
    setControlRevision(revision=>revision+1)
    return hzToDisplayValue(result.actualCenterHz,centerUnit)
  }
  const commitManualAttenuation=async(valueDb:number):Promise<number|false>=>{if(!hardware){set('attenuationDb',valueDb);return valueDb}useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{const response=await analyzerApi.put<AnalyzerSettingsApi|{settings:AnalyzerSettingsApi}>('/api/analyzer/amplitude/attenuation',{mode:'manual',attenuation_db:valueDb});const state='settings'in response?response.settings:response;applyState(state);return state.actual.attenuation_db??false}catch(error){useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'Configuration failed'});try{applyState(await analyzerApi.settings())}catch{/* preserve the entered draft and original error */}return false}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const commitAmplitudeOffset=async(valueDb:number):Promise<number|false>=>{if(!hardware){set('amplitudeOffsetDb',valueDb);return valueDb}useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{const response=await analyzerApi.put<AnalyzerSettingsApi|{settings:AnalyzerSettingsApi}>('/api/analyzer/amplitude/offset',{amplitude_offset_db:valueDb});const state='settings'in response?response.settings:response;applyState(state);return state.actual.amplitude_offset_db??false}catch(error){useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'Configuration failed'});return false}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const commitIfAgcTarget=async(value:number):Promise<number|false>=>{if(!hardware){set('ifAgcTargetDbfs',value);return value}useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{const state=await analyzerApi.put<AnalyzerSettingsApi>('/api/analyzer/amplitude/if-agc/target',{target_dbfs:value});applyState(state);return state.actual.if_agc_target_dbfs??false}catch(error){useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'IF AGC target configuration failed'});return false}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const commitIfAgcPeriod=async(value:number):Promise<number|false>=>{if(!hardware){set('ifAgcPeriodS',value);return value}useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{const state=await analyzerApi.put<AnalyzerSettingsApi>('/api/analyzer/amplitude/if-agc/period',{period_s:value});applyState(state);return state.actual.if_agc_period_s??false}catch(error){useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'IF AGC period configuration failed'});return false}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const changeIfAgcPeriodMode=(mode:string)=>{const value=mode==='one-shot'?-1:mode==='dynamic'?0:periodicSeconds.current;void commitIfAgcPeriod(value)}
  const disabled=loading||runtime.reconfiguring||runtime.playbackActive
  const commitTradeoff=async(index:number)=>{const previous=useDeviceStore.getState().resolutionTradeoffIndex;useRuntimeStore.getState().update({reconfiguring:true,lastError:undefined});try{if(!hardware){const step=capabilities.resolution_tradeoff_steps[index];if(!step)throw new Error('Invalid resolution trade-off step');useDeviceStore.setState({rbwMode:'manual',rbwHz:step.actual_rbw_hz,resolutionTradeoffIndex:index,resolutionTradeoffState:'matched'});const generation=useRuntimeStore.getState().configurationGeneration+1;useRuntimeStore.getState().update({configurationGeneration:generation,pointCount:step.point_count,actualRbwHz:step.actual_rbw_hz,spectrumFps:step.spectrum_publish_fps,waterfallRowsPerSecond:step.waterfall_rows_per_second,waterfallRowsPerBatch:step.waterfall_rows_per_batch,visibleWaterfallRows:Math.round(step.waterfall_rows_per_second*5),webglTargetFps:step.webgl_target_fps});setControlRevision(revision=>revision+1);return}const response=await analyzerApi.put<{actual_index:number;spectrum_publish_fps:number;webgl_target_fps:number;waterfall_rows_per_second:number;waterfall_rows_per_batch:number;visible_rows:number;settings:AnalyzerSettingsApi}>('/api/analyzer/resolution-tradeoff',{index});applyState(response.settings);useRuntimeStore.getState().update({webglTargetFps:response.webgl_target_fps,waterfallRowsPerSecond:response.waterfall_rows_per_second,waterfallRowsPerBatch:response.waterfall_rows_per_batch,visibleWaterfallRows:response.visible_rows})}catch(error){useDeviceStore.getState().set('resolutionTradeoffIndex',previous);useRuntimeStore.getState().update({lastError:error instanceof Error?error.message:'Trade-off configuration failed'});if(hardware)try{applyState(await analyzerApi.settings())}catch{/* keep original error */}throw error}finally{useRuntimeStore.getState().update({reconfiguring:false})}}
  const stageManualMode=()=>{const state=useDeviceStore.getState();const runtimeState=useRuntimeStore.getState();const matched=capabilities.resolution_tradeoff_steps.find(step=>step.point_count===runtimeState.pointCount&&Math.abs(step.actual_rbw_hz-state.rbwHz)<=Math.max(2,step.actual_rbw_hz*1e-4));useDeviceStore.setState({rbwMode:'manual',resolutionTradeoffIndex:matched?.index??state.resolutionTradeoffIndex,resolutionTradeoffState:'pending'})}
  const preampOptions=capabilities.preamplifier_modes.map(value=>({value,label:labels[value]??value}))
  const gainOptions=capabilities.gain_strategy_modes.map(value=>({value,label:labels[value]??value}))
  const windowOptions=capabilities.window_modes.map(value=>({value,label:labels[value]??value}))
  const detectorOptions=capabilities.detector_modes.map(value=>({value,label:labels[value]??value}))
  return <aside className="control-sidebar">
    <div className="sidebar-title"><div><b>ANALYZER CONTROL</b><span>DEVICE SETTINGS</span></div><div className="sidebar-title-actions"><button type="button" onClick={onResetLayout} disabled={!onResetLayout} title="Reset right dock width">Reset layout</button><span className="live-dot">● {runtime.reconfiguring?'RECONFIGURING':runtime.playbackActive?'PLAYBACK':'LIVE'}</span></div></div>
    <div className="sidebar-scroll">
      {runtime.lastError&&<div className="control-error" role="alert">{runtime.lastError}</div>}
      <ControlSection title="Frequency" defaultOpen={defaultSectionsOpen}>
        <NumericControl label="Center frequency" value={hzToDisplayValue(d.centerHz,centerUnit)} unit={centerUnit} unitOptions={CENTER_FREQUENCY_UNITS} unitPrecisions={{GHz:9,MHz:6}} onUnitChange={unit=>setCenterUnit(unit as CenterFrequencyUnit)} convertUnitValue={(value,fromUnit,toUnit)=>hzToDisplayValue(displayValueToHz(value,fromUnit as CenterFrequencyUnit),toUnit as CenterFrequencyUnit)} step={hzToDisplayValue(d.stepHz,centerUnit)} precision={centerFrequencyPrecision(centerUnit)} resetToken={controlRevision} verifiedCommit validateValue={validCenterDisplayValue} onInvalid={rejectCenterFrequency} disabled={disabled||runtime.frequencyScan.running||!supported('center_frequency_hz')} onChange={commitCenterFrequency}/>
        <NumericControl label="Step frequency" value={d.stepHz/1e6} unit="MHz" step={1} min={.001} max={1000} precision={3} disabled={disabled} onChange={(v)=>set('stepHz',v*1e6)}/>
      </ControlSection>
      <ControlSection title="Frequency Scan" defaultOpen={defaultSectionsOpen}><FrequencyScanControl minimumFrequencyHz={centerMinimumHz} maximumFrequencyHz={centerMaximumHz} disabled={loading||runtime.playbackActive||!supported('center_frequency_hz')}/></ControlSection>
      <ControlSection title="RF Path" defaultOpen={defaultSectionsOpen}><RfPathControl/></ControlSection>
      <ControlSection title="Amplitude" defaultOpen={defaultSectionsOpen}>
        <NumericControl label="Reference level" value={d.referenceDbm} unit="dBm" step={REFERENCE_LEVEL_STEP_DB} min={capabilities.reference_level_min_dbm??-200} max={capabilities.reference_level_max_dbm??100} resetToken={controlRevision} disabled={disabled||!supported('reference_level_dbm')} onChange={(v)=>commit('/api/analyzer/amplitude/reference-level',{reference_level_dbm:v},()=>set('referenceDbm',v))}/>
        <SelectControl label="Attenuation mode" value={d.attenuationAutomatic?'auto':'manual'} disabled={disabled||!supported('attenuation_db')} options={options([['Automatic','auto'],['Manual','manual']])} onChange={(mode)=>commit('/api/analyzer/amplitude/attenuation',mode==='auto'?{mode:'auto'}:{mode:'manual',attenuation_db:d.attenuationDb},()=>set('attenuationAutomatic',mode==='auto'))}/>
        <NumericControl label="Attenuation" value={d.attenuationDb} unit="dB" step={hardware?SAN90_ATTENUATION_STEP_DB:1} min={hardware?3:0} max={hardware?33:127} resetToken={controlRevision} verifiedCommit disabled={disabled||d.attenuationAutomatic||!supported('attenuation_db')} onChange={commitManualAttenuation}/>
        <SelectControl label="Preamplifier" value={d.preamplifier} options={preampOptions} disabled={disabled||!supported('preamplifier')} onChange={(v)=>commit('/api/analyzer/amplitude/preamplifier',{mode:v},()=>set('preamplifier',v))}/>
        <SelectControl label="Gain strategy" value={d.gainStrategy} options={gainOptions} disabled={disabled||!supported('gain_strategy')} onChange={(v)=>commit('/api/analyzer/amplitude/gain-strategy',{mode:v},()=>set('gainStrategy',v))}/>
        <NumericControl label="Amplitude offset" value={d.amplitudeOffsetDb} unit="dB" step={capabilities.numeric_ranges?.amplitude_offset_db?.step??AMPLITUDE_OFFSET_STEP_DB} min={capabilities.numeric_ranges?.amplitude_offset_db?.minimum??AMPLITUDE_OFFSET_MIN_DB} max={capabilities.numeric_ranges?.amplitude_offset_db?.maximum??AMPLITUDE_OFFSET_MAX_DB} precision={1} resetToken={controlRevision} verifiedCommit disabled={disabled||!supported('amplitude_offset_db')} onChange={commitAmplitudeOffset}/>
        <ToggleControl label="IF AGC" value={d.ifAgc} disabled={disabled||!supported('if_agc_enabled')} onChange={(v)=>{void commit('/api/analyzer/amplitude/if-agc',{enabled:v},()=>set('ifAgc',v))}}/>
        <NumericControl label="IF AGC target" value={d.ifAgcTargetDbfs} unit="dBFS" step={capabilities.numeric_ranges?.if_agc_target_dbfs?.step??1} min={capabilities.numeric_ranges?.if_agc_target_dbfs?.minimum??IF_AGC_TARGET_MIN_DBFS} max={capabilities.numeric_ranges?.if_agc_target_dbfs?.maximum??IF_AGC_TARGET_MAX_DBFS} resetToken={controlRevision} verifiedCommit disabled={disabled||!d.ifAgc||!supported('if_agc_target_dbfs')} onChange={commitIfAgcTarget}/>
        <SelectControl label="IF AGC period mode" value={d.ifAgcPeriodS<0?'one-shot':d.ifAgcPeriodS===0?'dynamic':'periodic'} disabled={disabled||!d.ifAgc||!supported('if_agc_period_s')} title="One-shot runs once before sampling; Dynamic uses 0 s; Periodic runs at a positive interval." options={options([['One-shot','one-shot'],['Dynamic','dynamic'],['Periodic','periodic']])} onChange={changeIfAgcPeriodMode}/>
        {d.ifAgcPeriodS>0&&<NumericControl label="IF AGC period" value={d.ifAgcPeriodS} unit="s" step={capabilities.numeric_ranges?.if_agc_period_s?.step??1} min={Number.MIN_VALUE} max={capabilities.numeric_ranges?.if_agc_period_s?.maximum??IF_AGC_PERIOD_MAX_S} precision={3} resetToken={controlRevision} verifiedCommit disabled={disabled||!d.ifAgc||!supported('if_agc_period_s')} onChange={commitIfAgcPeriod}/>}
        <div className="control-row"><label>IF AGC gain</label><div className="numeric-control"><span><input aria-label="IF AGC gain" disabled readOnly value={d.ifAgcGainDb==null?'—':String(d.ifAgcGainDb)}/><em>dB</em></span><button aria-label="Decrease IF AGC gain" disabled>−</button><button aria-label="Increase IF AGC gain" disabled>+</button></div></div>
      </ControlSection>
      <ControlSection title="Bandwidth" defaultOpen={defaultSectionsOpen}>
        <SelectControl label="RBW mode" value={d.rbwMode} disabled={disabled||!capabilities.supports_rbw_control} options={options([['Auto','auto'],['Manual','manual']])} onChange={(mode)=>{if(mode==='manual'){if(capabilities.supports_resolution_tradeoff)stageManualMode();else void commit('/api/analyzer/bandwidth/rbw',{mode:'manual',rbw_hz:d.rbwHz},()=>set('rbwMode','manual'))}else void commit('/api/analyzer/bandwidth/rbw',{mode:'auto'},()=>{const safe=capabilities.resolution_tradeoff_steps.at(-1);useDeviceStore.setState({rbwMode:'auto',rbwHz:safe?.actual_rbw_hz??60306.09130859375,resolutionTradeoffIndex:safe?.index??7,resolutionTradeoffState:'auto'});useRuntimeStore.getState().update({pointCount:safe?.point_count??3328,actualRbwHz:safe?.actual_rbw_hz??60306.09130859375,waterfallRowsPerSecond:60,waterfallRowsPerBatch:1,visibleWaterfallRows:300,webglTargetFps:60})})}}/>
        {d.rbwMode==='manual'&&capabilities.supports_resolution_tradeoff&&<ResolutionTradeoffControl key={`${d.resolutionTradeoffState}-${d.resolutionTradeoffIndex}`} steps={capabilities.resolution_tradeoff_steps} actualIndex={d.resolutionTradeoffIndex} custom={d.resolutionTradeoffState==='custom'} staged={d.resolutionTradeoffState==='pending'} disabled={disabled} onCommit={commitTradeoff}/>} 
        {d.rbwMode==='manual'&&<details className="advanced-rbw"><summary>Advanced numeric RBW</summary><NumericControl label="RBW request" value={d.rbwHz/1e3} unit="kHz" step={10} min={(capabilities.rbw_min_hz??1)/1e3} max={(capabilities.rbw_max_hz??1e9)/1e3} precision={3} disabled={disabled||!capabilities.supports_rbw_control} onChange={(v)=>commit('/api/analyzer/bandwidth/rbw',{mode:'manual',rbw_hz:v*1e3},()=>{const requested=v*1e3;const matched=capabilities.resolution_tradeoff_steps.find(step=>Math.abs(step.requested_rbw_hz-requested)<.5||Math.abs(step.actual_rbw_hz-requested)<2);if(matched)useDeviceStore.setState({rbwMode:'manual',rbwHz:matched.actual_rbw_hz,resolutionTradeoffIndex:matched.index,resolutionTradeoffState:'matched'});else useDeviceStore.setState({rbwMode:'manual',rbwHz:requested,resolutionTradeoffState:'custom'})})}/></details>}
        <div className="control-row"><label>VBW</label><div className="numeric-control read-only-numeric"><span><input aria-label="VBW" readOnly tabIndex={-1} value={vbwReadback}/><em>{activeVbwUnit}</em></span></div></div>
        <SelectControl label="Window function" value={d.window} disabled={disabled||!supported('window')} options={windowOptions} onChange={(v)=>commit('/api/analyzer/sweep/window',{window:v},()=>set('window',v))}/>
      </ControlSection>
      <ControlSection title="Detection" defaultOpen={defaultSectionsOpen}><SelectControl label="Detector mode" value={d.detector} disabled={disabled||!supported('detector')} options={detectorOptions} onChange={(v)=>commit('/api/analyzer/detection/detector',{detector:v},()=>set('detector',v))}/></ControlSection>
      <ControlSection title="Record" defaultOpen={defaultSectionsOpen}><RecordControl disabled={runtime.playbackActive}/></ControlSection>
      <ControlSection title="Playback" defaultOpen={defaultSectionsOpen}><PlaybackControl/></ControlSection>
    </div>
  </aside>
}
