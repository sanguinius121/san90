import { useEffect, useRef, useState } from 'react'
type CommitResult = number | false | void
interface NumericControlProps {
  label: string
  value: number
  unit: string
  step: number
  min?: number
  max?: number
  disabled?: boolean
  onChange: (value: number) => CommitResult | Promise<CommitResult>
  precision?: number
  resetToken?: number
  verifiedCommit?: boolean
  unitOptions?: readonly string[]
  unitPrecisions?: Readonly<Record<string, number>>
  onUnitChange?: (unit: string) => void
  convertUnitValue?: (value: number, fromUnit: string, toUnit: string) => number
  validateValue?: (value: number) => boolean
  onInvalid?: () => void
}
const formatValue=(value:number,precision:number)=>String(Number(value.toFixed(precision)))
export function NumericControl({
  label,
  value,
  unit,
  step,
  min=-Infinity,
  max=Infinity,
  disabled,
  onChange,
  precision=0,
  resetToken=0,
  verifiedCommit=false,
  unitOptions,
  unitPrecisions,
  onUnitChange,
  convertUnitValue,
  validateValue,
  onInvalid,
}: NumericControlProps) {
  const [draft,setDraft]=useState(formatValue(value,precision)); const editing=useRef(false); const focused=useRef(false); const pending=useRef(false); const timer=useRef<number|undefined>(undefined)
  useEffect(()=>{if(!editing.current&&!focused.current&&!pending.current)setDraft(formatValue(value,precision))},[value,resetToken,precision])
  useEffect(()=>()=>window.clearTimeout(timer.current),[])
  const clearPending = () => { window.clearTimeout(timer.current); timer.current=undefined }
  const reject = () => {
    clearPending()
    onInvalid?.()
    if (!verifiedCommit) {
      editing.current=false
      setDraft(formatValue(value,precision))
    }
  }
  const change = (next: number) => {
    if (!Number.isFinite(next) || (validateValue && !validateValue(next))) {
      reject()
      return
    }
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
  const commitValue=(text:string)=>{if(!text.trim()){reject();return}const parsed=Number(text);if(Number.isFinite(parsed))change(parsed);else reject()}
  const commit=()=>{if(editing.current&&!pending.current)commitValue(draft)}
  const typed=(next:string)=>{setDraft(next);editing.current=true;clearPending();if(!verifiedCommit)timer.current=window.setTimeout(()=>{if(editing.current)commitValue(next)},600)}
  const draftValue=()=>{const parsed=Number(draft);return Number.isFinite(parsed)?parsed:value}
  const selectUnit=(nextUnit:string)=>{
    if(nextUnit===unit)return
    const parsed=Number(draft)
    const sourceValue=draft.trim()&&Number.isFinite(parsed)?parsed:value
    if(convertUnitValue)setDraft(formatValue(convertUnitValue(sourceValue,unit,nextUnit),unitPrecisions?.[nextUnit]??precision))
    onUnitChange?.(nextUnit)
  }
  return <div className={`control-row ${disabled ? 'is-disabled' : ''}`}>
    <label>{label}</label><div className="numeric-control"><span><input aria-label={label} disabled={disabled} value={draft} onChange={event=>typed(event.target.value)} onFocus={()=>{focused.current=true}} onBlur={()=>{focused.current=false;if(editing.current)commit();else setDraft(formatValue(value,precision))}} onKeyDown={event=>{if(event.key==='Enter')commit();if(event.key==='Escape'){clearPending();editing.current=false;setDraft(formatValue(value,precision))}}}/>{unitOptions?<select className="numeric-unit-select" aria-label={`${label} unit`} disabled={disabled} value={unit} onChange={event=>selectUnit(event.target.value)}>{unitOptions.map(option=><option key={option} value={option}>{option}</option>)}</select>:<em>{unit}</em>}</span>
      <button aria-label={`Decrease ${label}`} disabled={disabled} onClick={()=>change(draftValue()-step)}>−</button><button aria-label={`Increase ${label}`} disabled={disabled} onClick={()=>change(draftValue()+step)}>+</button>
    </div>
  </div>
}
