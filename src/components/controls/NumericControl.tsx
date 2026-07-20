import { useEffect, useRef, useState } from 'react'
interface NumericControlProps { label: string; value: number; unit: string; step: number; min?: number; max?: number; disabled?: boolean; onChange: (value: number) => void; precision?: number; resetToken?: number }
const formatValue=(value:number,precision:number)=>String(Number(value.toFixed(precision)))
export function NumericControl({ label, value, unit, step, min=-Infinity, max=Infinity, disabled, onChange, precision=0, resetToken=0 }: NumericControlProps) {
  const [draft,setDraft]=useState(formatValue(value,precision)); const editing=useRef(false); const timer=useRef<number|undefined>(undefined)
  useEffect(()=>{if(!editing.current)setDraft(formatValue(value,precision))},[value,resetToken,precision])
  useEffect(()=>()=>window.clearTimeout(timer.current),[])
  const clearPending = () => { window.clearTimeout(timer.current); timer.current=undefined }
  const change = (next: number) => { clearPending(); const accepted=Math.max(min,Math.min(max,next)); setDraft(formatValue(accepted,precision)); editing.current=false; onChange(accepted) }
  const commitValue=(text:string)=>{const parsed=Number(text);if(Number.isFinite(parsed))change(parsed);else setDraft(formatValue(value,precision))}
  const commit=()=>{if(editing.current)commitValue(draft)}
  const typed=(next:string)=>{setDraft(next);editing.current=true;clearPending();timer.current=window.setTimeout(()=>{if(editing.current)commitValue(next)},600)}
  const draftValue=()=>{const parsed=Number(draft);return Number.isFinite(parsed)?parsed:value}
  return <div className={`control-row ${disabled ? 'is-disabled' : ''}`}>
    <label>{label}</label><div className="numeric-control"><span><input aria-label={label} disabled={disabled} value={draft} onChange={event=>typed(event.target.value)} onFocus={()=>{editing.current=true}} onBlur={commit} onKeyDown={event=>{if(event.key==='Enter')commit();if(event.key==='Escape'){clearPending();editing.current=false;setDraft(formatValue(value,precision))}}}/><em>{unit}</em></span>
      <button aria-label={`Decrease ${label}`} disabled={disabled} onClick={()=>change(draftValue()-step)}>−</button><button aria-label={`Increase ${label}`} disabled={disabled} onClick={()=>change(draftValue()+step)}>+</button>
    </div>
  </div>
}
