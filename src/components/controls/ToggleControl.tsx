import { useRfSidebarLocalization } from '../../data/rfSidebarLocalization'

interface ToggleControlProps { label: string; value: boolean; disabled?:boolean; onChange: (value: boolean) => void }
export function ToggleControl({label,value,disabled,onChange,hint}:{hint?:string}&ToggleControlProps) {
  const common=useRfSidebarLocalization('Common')
  return <div className={`control-row ${disabled?'is-disabled':''}`} title={hint}><label>{label}</label><button disabled={disabled} className={`toggle-control ${value?'is-on':''}`} role="switch" aria-checked={value} onClick={()=>onChange(!value)}><span>{common.t('OFF')}</span><span>{common.t('ON')}</span></button></div>
}
