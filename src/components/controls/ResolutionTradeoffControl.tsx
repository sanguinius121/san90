import { useState, type KeyboardEvent } from 'react'
import type { ResolutionTradeoffStepApi } from '../../data/controlApi'
import { useRfSidebarLocalization } from '../../data/rfSidebarLocalization'

interface Props {steps:ResolutionTradeoffStepApi[];actualIndex:number;custom:boolean;staged?:boolean;disabled?:boolean;onCommit:(index:number)=>Promise<void>}
const hz=(value:number)=>value>=1e6?`${(value/1e6).toFixed(3)} MHz`:`${(value/1e3).toFixed(3)} kHz`

export function ResolutionTradeoffControl({steps,actualIndex,custom,staged=false,disabled,onCommit}:Props){
  const text=useRfSidebarLocalization('Bandwidth')
  const [preview,setPreview]=useState(actualIndex);const [committing,setCommitting]=useState(false)
  if(!steps.length)return null
  const selected=steps[Math.max(0,Math.min(steps.length-1,preview))]
  const changed=preview!==actualIndex||custom||staged
  const commit=async()=>{if(disabled||committing||(!changed&&!custom))return;setCommitting(true);try{await onCommit(preview)}catch{setPreview(actualIndex)}finally{setCommitting(false)}}
  const keyUp=(event:KeyboardEvent<HTMLInputElement>)=>{if(['ArrowLeft','ArrowRight','Home','End','Enter'].includes(event.key))void commit()}
  return <div className={`tradeoff-control ${disabled||committing?'is-disabled':''}`}>
    <div className="tradeoff-heading" title={text.hint('Time/Frequency resolution trade-off')}><b>{text.t('Time/Frequency resolution trade-off')}</b><span>{text.t(committing?'APPLYING':changed?'EXPECTED':'ACTIVE')}</span></div>
    <div className="tradeoff-scale"><span>{text.t('Time')}</span><input aria-label={text.t('Time/Frequency resolution trade-off')} type="range" min={0} max={steps.length-1} step={1} list="resolution-tradeoff-stops" value={preview} disabled={disabled||committing} onChange={event=>setPreview(Number(event.target.value))} onPointerUp={()=>void commit()} onKeyUp={keyUp}/><datalist id="resolution-tradeoff-stops">{steps.map(step=><option key={step.id} value={step.index}/>)}</datalist><span>{text.t('Frequency')}</span></div>
    <div className="tradeoff-preview" aria-live="polite">
      <span><i>{text.t('Requested RBW')}</i><b>{hz(selected.requested_rbw_hz)}</b></span>
      <span><i>{text.t(changed?'Expected RBW':'Actual RBW')}</i><b>{hz(selected.actual_rbw_hz)}</b></span>
      <span><i>{text.t('FFT size')}</i><b>{selected.fft_size?.toLocaleString()??'—'}</b></span>
      <span><i>{text.t('Spectrum points')}</i><b>{selected.point_count.toLocaleString()}</b></span>
      <span><i>{text.t('Trace rate')}</i><b>~{((selected.measured_trace_rate_hz??0)/1000).toFixed(1)} k/s</b></span>
      <span><i>{text.t('Spectrum display')}</i><b>60 FPS</b></span>
      <span><i>{text.t('Bin spacing')}</i><b>{hz(selected.frequency_bin_spacing_hz)}/bin</b></span>
      <span><i>{text.t('Waterfall')}</i><b>{selected.waterfall_rows_per_second} rows/s</b></span>
      <span><i>{text.t('Waterfall batch')}</i><b>{selected.waterfall_rows_per_batch} rows</b></span>
      <span><i>{text.t('Time resolution')}</i><b>{(selected.nominal_time_per_row_s*1000).toFixed(2)} ms/row</b></span>
      <span><i>{text.t('Traces / row')}</i><b>~{selected.measured_trace_rate_hz?Math.round(selected.measured_trace_rate_hz/selected.waterfall_rows_per_second):'—'}</b></span>
      <span><i>{text.t('Visible span')}</i><b>5.0 s</b></span>
      {custom&&preview===actualIndex&&<span className="tradeoff-custom">{text.t('CUSTOM RBW')}</span>}
    </div>
  </div>
}
