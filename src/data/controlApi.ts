export interface ResolutionTradeoffStepApi {id:string;index:number;requested_rbw_hz:number;actual_rbw_hz:number;point_count:number;fft_size:number|null;measured_trace_rate_hz:number|null;spectrum_publish_fps:number;spectrum_render_fps:number;webgl_target_fps:number;waterfall_rows_per_second:number;waterfall_batches_per_second:number;waterfall_rows_per_batch:number;frequency_bin_spacing_hz:number;nominal_time_per_row_s:number;actual_span_hz:number;label:string|null;poi_s:number|null}
export interface AnalyzerCapabilitiesApi {
  source:string
  supported_controls:string[]
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
  requested:{center_frequency_hz:number;reference_level_dbm:number;attenuation_db:number|null;preamplifier:string|null;gain_strategy:string|null;rbw_hz:number|null;rbw_mode:string;window:string|null;detector:string|null}
  actual:{center_frequency_hz:number;start_frequency_hz:number;stop_frequency_hz:number;span_hz:number;reference_level_dbm:number;attenuation_db:number|null;attenuation_automatic:boolean;preamplifier:string|null;gain_strategy:string|null;rbw_hz:number;rbw_mode:string;window:string|null;detector:string|null;fft_size:number;scale_to_dbm:number|null;offset_to_dbm:number|null;point_count:number;resolution_tradeoff_index:number|null;resolution_tradeoff_state:'auto'|'matched'|'custom';resolution_tradeoff_step_id:string|null;frequency_bin_spacing_hz:number|null}
  configuration_generation:number
}

const base=`http://${location.hostname}:8000`
async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const response=await fetch(`${base}${path}`,{...init,headers:{'Content-Type':'application/json',...(init?.headers??{})}})
  const body=await response.json().catch(()=>({}))
  if(!response.ok) throw new Error(body?.error?.message??body?.detail??`Analyzer request failed (${response.status})`)
  return body as T
}
export const analyzerApi={
  capabilities:()=>request<AnalyzerCapabilitiesApi>('/api/analyzer/capabilities'),
  settings:()=>request<AnalyzerSettingsApi>('/api/analyzer/settings'),
  put:<T>(path:string,body:object)=>request<T>(path,{method:'PUT',body:JSON.stringify(body)}),
}
