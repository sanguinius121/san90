interface ToggleControlProps { label: string; value: boolean; disabled?:boolean; onChange: (value: boolean) => void }
export function ToggleControl({label,value,disabled,onChange}:ToggleControlProps) {
  return <div className={`control-row ${disabled?'is-disabled':''}`}><label>{label}</label><button disabled={disabled} className={`toggle-control ${value?'is-on':''}`} role="switch" aria-checked={value} onClick={()=>onChange(!value)}><span>OFF</span><span>ON</span></button></div>
}
