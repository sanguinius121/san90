import type { SelectOption } from '../../types'
interface SelectControlProps { label: string; value: string; options: SelectOption[]; disabled?:boolean; title?:string; onChange: (value: string) => void }
export function SelectControl({label,value,options,disabled,title,onChange}: SelectControlProps) {
  return <div className={`control-row ${disabled?'is-disabled':''}`} title={title}><label>{label}</label><select aria-label={label} value={value} disabled={disabled} onChange={(e)=>onChange(e.target.value)}>{options.map((option)=><option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
}
