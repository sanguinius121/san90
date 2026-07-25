export interface ResolutionTradeoffStepApi {id:string;index:number;requested_rbw_hz:number;actual_rbw_hz:number;point_count:number;fft_size:number|null;measured_trace_rate_hz:number|null;spectrum_publish_fps:number;spectrum_render_fps:number;webgl_target_fps:number;waterfall_rows_per_second:number;waterfall_batches_per_second:number;waterfall_rows_per_batch:number;frequency_bin_spacing_hz:number;nominal_time_per_row_s:number;actual_span_hz:number;label:string|null;poi_s:number|null}
export interface AnalyzerCapabilitiesApi {
  source:string
  supported_controls:string[]
  numeric_ranges?:Record<string,{minimum:number;maximum:number;step:number|null}>
  center_frequency_min_hz:number|null
  center_frequency_max_hz:number|null
  center_frequency_step_hz:number|null
  reference_level_min_dbm:number|null
  reference_level_max_dbm:number|null
  supported_attenuation_values_db:number[]|null
  supports_automatic_attenuation:boolean
  preamplifier_modes:string[]
  gain_strategy_modes:string[]
  requires_restart_for_frequency:boolean
  requires_restart_for_amplitude:boolean
  supports_rbw_control:boolean
  rbw_control_mode:string|null
  supported_rbw_values_hz:number[]|null
  rbw_min_hz:number|null
  rbw_max_hz:number|null
  rbw_is_discrete:boolean|null
  rbw_is_profile_based:boolean|null
  rbw_changes_point_count:boolean|null
  rbw_changes_span:boolean|null
  rbw_requires_restart:boolean
  window_modes:string[]
  detector_modes:string[]
  window_requires_restart:boolean
  detector_requires_restart:boolean
  supports_resolution_tradeoff:boolean
  resolution_tradeoff_steps:ResolutionTradeoffStepApi[]
  resolution_tradeoff_min_index:number|null
  resolution_tradeoff_max_index:number|null
  resolution_tradeoff_direction:Record<string,string>
  default_resolution_tradeoff_index:number|null
  supports_auto_rbw:boolean
}

export interface AnalyzerSettingsApi {
  requested:{center_frequency_hz:number;reference_level_dbm:number;attenuation_db:number|null;preamplifier:string|null;gain_strategy:string|null;rbw_hz:number|null;rbw_mode:string;window:string|null;detector:string|null;amplitude_offset_db?:number}
  actual:{center_frequency_hz:number;start_frequency_hz:number;stop_frequency_hz:number;span_hz:number;reference_level_dbm:number;attenuation_db:number|null;attenuation_automatic:boolean;preamplifier:string|null;gain_strategy:string|null;rbw_hz:number;rbw_mode:string;window:string|null;detector:string|null;fft_size:number;scale_to_dbm:number|null;offset_to_dbm:number|null;point_count:number;resolution_tradeoff_index:number|null;resolution_tradeoff_state:'auto'|'matched'|'custom';resolution_tradeoff_step_id:string|null;frequency_bin_spacing_hz:number|null;amplitude_offset_db?:number}
  configuration_generation:number
}

export interface FrequencyScanEntryApi {
  id:string
  enabled:boolean
  center_frequency_hz:number
  duration_seconds:number
}

export interface FrequencyScanApi {
  entries:FrequencyScanEntryApi[]
  running:boolean
  state:'idle'|'tuning'|'dwelling'|'stopping'|'error'
  active_entry_id:string|null
  active_index:number|null
  active_count:number
  verified_center_frequency_hz:number|null
  dwell_duration_seconds:number|null
  remaining_dwell_seconds:number|null
  last_error:string|null
}

export type RfPathId = 'rf1'|'rf2'|'rf3'|'rf4'|'rf5'|'rf6'|'rf7'|'rf8'
export interface RfSwitchPathApi {id:RfPathId;rf_channel:string;address:number;label:string;external_lna:boolean}
export interface RfSwitchCapabilitiesApi {enabled:boolean;default_path:RfPathId;selection_policy:string;paths:RfSwitchPathApi[]}
export interface RfSwitchStatusApi {
  connection_state:'disabled'|'connecting'|'available'|'disconnected'|'reconnecting'|'error'
  hardware_present:boolean
  available:boolean;connected:boolean;backend:string;simulated:boolean
  requested_path:RfPathId|null;requested_port:RfPathId|null
  reported_path:RfPathId|null;reported_port:RfPathId|null;expected_fail_safe_path:RfPathId|null
  raw_address:number|null;raw_gpio_value:number|null;gpio_value:number|null
  readback_matches_request:boolean;verification:'unavailable'|'unverified'|'verified'|'mismatch'
  last_error:string|null;reconnect_attempts:number;last_connected_at:number|null;last_disconnected_at:number|null;updated_at_monotonic:number
}

const base=`http://${location.hostname}:8000`
async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(`${base}${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers??{})}})
  const body=await response.json().catch(()=>({}))
  if(!response.ok) throw new Error(body?.error?.message??body?.detail?.message??body?.detail??`Analyzer request failed (${response.status})`)
  return body as T
}
export const analyzerApi={
  capabilities:()=>request<AnalyzerCapabilitiesApi>('/api/analyzer/capabilities'),
  settings:()=>request<AnalyzerSettingsApi>('/api/analyzer/settings'),
  put:<T>(path:string,body:object)=>request<T>(path,{method:'PUT',body:JSON.stringify(body)}),
  post:<T>(path:string,body?:object)=>request<T>(path,{method:'POST',...(body?{body:JSON.stringify(body)}:{})}),
  frequencyScanStatus:()=>request<FrequencyScanApi>('/api/analyzer/frequency-scan/status'),
  configureFrequencyScan:(entries:FrequencyScanEntryApi[])=>request<FrequencyScanApi>('/api/analyzer/frequency-scan/config',{method:'PUT',body:JSON.stringify({entries})}),
  startFrequencyScan:()=>request<FrequencyScanApi>('/api/analyzer/frequency-scan/start',{method:'POST'}),
  stopFrequencyScan:()=>request<FrequencyScanApi>('/api/analyzer/frequency-scan/stop',{method:'POST'}),
}
export const rfSwitchApi={
  capabilities:()=>request<RfSwitchCapabilitiesApi>('/api/rf-switch/capabilities'),
  status:()=>request<RfSwitchStatusApi>('/api/rf-switch/status'),
  setPath:(path:RfPathId)=>request<RfSwitchStatusApi>('/api/rf-switch/path',{method:'PUT',body:JSON.stringify({path})}),
}
