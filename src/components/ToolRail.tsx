import { Activity, Crosshair, ChartNoAxesCombined, Maximize, MousePointer2, Move, RadioTower, Search, Wifi } from 'lucide-react'
import { useDisplayStore, useRuntimeStore } from '../stores'
import { liveFrames } from '../data/liveFrames'
import { spectrumBinFrequencyHz } from '../data/frequencyBins'
import type { ToolMode } from '../types'

const tools: {id:ToolMode;label:string;icon:typeof Activity}[]=[
  {id:'graph',label:'Graph',icon:ChartNoAxesCombined},{id:'trace',label:'Trace',icon:Activity},{id:'peak',label:'Peak Search',icon:Search},
  {id:'marker',label:'Marker',icon:Crosshair},{id:'pan',label:'Pan',icon:Move},{id:'zoom',label:'Zoom',icon:Maximize},
]
export function ToolRail() {
  const active=useDisplayStore((s)=>s.activeTool); const setTool=useDisplayStore((s)=>s.setTool); const connection=useRuntimeStore((s)=>s.connection)
  const activate=(id:ToolMode)=>{ setTool(id); if(id==='peak'){ const frame=liveFrames.getLatest(); if(!frame)return; const view=useDisplayStore.getState().viewport; const first=Math.floor(view.start*(frame.values.length-1)); const last=Math.ceil(view.end*(frame.values.length-1)); let bin=first; for(let i=first+1;i<=last;i++)if(frame.values[i]>frame.values[bin])bin=i; useDisplayStore.getState().setMarker({bin,frequencyHz:spectrumBinFrequencyHz(frame,bin),amplitudeDbm:frame.values[bin]}) } }
  return <nav className="tool-rail" aria-label="Analysis tools"><div className="rail-brand"><RadioTower size={22}/><span>RF</span></div>
    <div className="rail-tools">{tools.map((tool)=>{const Icon=tool.icon;return <button key={tool.id} className={active===tool.id?'is-active':''} onClick={()=>activate(tool.id)} title={tool.label}><Icon size={21}/><span>{tool.label}</span></button>})}</div>
    <div className="rail-state"><Wifi size={16}/><span>{connection}</span><small>USB 3</small></div>
    <MousePointer2 className="rail-cursor" size={12}/>
  </nav>
}
