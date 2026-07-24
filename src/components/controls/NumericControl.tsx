import { useEffect, useRef, useState } from 'react'
type CommitResult = number | false | void
interface NumericControlProps { label: string; value: number; unit: string; step: number; min?: number; max?: number; disabled?: boolean; onChange: (value: number) => CommitResult | Promise<CommitResult>; precision?: number; resetToken?: number; verifiedCommit?: boolean }
const formatValue=(value:number,precision:number)=>String(Number(value.toFixed(precision)))
export function NumericControl({ label, value, unit, step, min=-Infinity, max=Infinity, disabled, onChange, precision=0, resetToken=0, verifiedCommit=false }: NumericControlProps) {
  const [draft,setDraft]=useState(formatValue(value,precision)); const editing=useRef(false); const focused=useRef(false); const pending=useRef(false); const timer=useRef<number|undefined>(undefined)
  useEffect(()=>{if(!editing.current&&!focused.current&&!pending.current)setDraft(formatValue(value,precision))},[value,resetToken,precision])
  useEffect(()=>()=>window.clearTimeout(timer.current),[])
  const clearPending = () => { window.clearTimeout(timer.current); timer.current=undefined }
  const change = (next: number) => {
    clearPending(); const accepted=Math.max(min,Math.min(max,next)); setDraft(formatValue(accepted,precision))
    if(!verifiedCommit){editing.current=false;onChange(accepted);return}
    if(pending.current)return
    pending.current=true;editing.current=true
    void Promise.resolve(onChange(accepted)).then(result=>{
      if(result===false)return
      editing.current=false
      setDraft(formatValue(typeof result==='number'?result:accepted,precision))
    }).finally(()=>{pending.current=false})
  }
  const commitValue=(text:string)=>{const parsed=Number(text);if(Number.isFinite(parsed))change(parsed);else{editing.current=false;setDraft(formatValue(value,precision))}}
  const commit=()=>{if(editing.current&&!pending.current)commitValue(draft)}
  const typed=(next:string)=>{setDraft(next);editing.current=true;clearPending();if(!verifiedCommit)timer.current=window.setTimeout(()=>{if(editing.current)commitValue(next)},600)}
  const draftValue=()=>{const parsed=Number(draft);return Number.isFinite(parsed)?parsed:value}
  return <div className={`control-row ${disabled ? 'is-disabled' : ''}`}>
    <label>{label}</label><div className="numeric-control"><span><input aria-label={label} disabled={disabled} value={draft} onChange={event=>typed(event.target.value)} onFocus={()=>{focused.current=true}} onBlur={()=>{focused.current=false;if(editing.current)commit();else setDraft(formatValue(value,precision))}} onKeyDown={event=>{if(event.key==='Enter')commit();if(event.key==='Escape'){clearPending();editing.current=false;setDraft(formatValue(value,precision))}}}/><em>{unit}</em></span>
      <button aria-label={`Decrease ${label}`} disabled={disabled} onClick={()=>change(draftValue()-step)}>−</button><button aria-label={`Increase ${label}`} disabled={disabled} onClick={()=>change(draftValue()+step)}>+</button>
    </div>
  </div>
}
