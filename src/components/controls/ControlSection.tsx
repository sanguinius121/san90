import { ChevronDown } from 'lucide-react'
import { useState, type ReactNode } from 'react'
export function ControlSection({title,children,defaultOpen=false}:{title:string;children:ReactNode;defaultOpen?:boolean}) {
  const [open,setOpen]=useState(defaultOpen)
  return <section className={`control-section ${open?'is-open':''}`}><button className="section-heading" onClick={()=>setOpen(!open)} aria-expanded={open}><span>{title}</span><ChevronDown size={14}/></button>{open&&<div className="section-body">{children}</div>}</section>
}
