import { Crosshair, MousePointer2, Move, RadioTower, ScanEye, Search, Wifi } from 'lucide-react'
import { useDisplayStore, useRuntimeStore } from '../stores'
import { liveFrames } from '../data/liveFrames'
import { spectrumBinFrequencyHz } from '../data/frequencyBins'
import type { ToolMode } from '../types'

const tools: {id:ToolMode;label:string;icon:typeof Search}[]=[
  {id:'peak',label:'Peak Search',icon:Search},
  {id:'marker',label:'Marker',icon:Crosshair},
  {id:'pan',label:'Pan',icon:Move},
]
export type DockPanel = 'rf' | 'ai-preview'

export function ToolRail({
  panel = 'rf',
  onPanelChange = () => undefined,
}: {
  panel?: DockPanel
  onPanelChange?: (panel: DockPanel) => void
} = {}) {
  const active=useDisplayStore((s)=>s.activeTool); const setTool=useDisplayStore((s)=>s.setTool); const connection=useRuntimeStore((s)=>s.connection)
  const activate=(id:ToolMode)=>{ setTool(id); if(id==='peak'){ const frame=liveFrames.getLatest(); if(!frame)return; const view=useDisplayStore.getState().viewport; const first=Math.floor(view.start*(frame.values.length-1)); const last=Math.ceil(view.end*(frame.values.length-1)); let bin=first; for(let i=first+1;i<=last;i++)if(frame.values[i]>frame.values[bin])bin=i; useDisplayStore.getState().setMarker({bin,frequencyHz:spectrumBinFrequencyHz(frame,bin),amplitudeDbm:frame.values[bin]}) } }
  return <nav className="tool-rail" aria-label="Analysis and sidebar navigation">
    <div className="rail-tools rail-panel-tools">
      <button className="rail-rf" onClick={()=>onPanelChange('rf')} title="RF Controls" aria-pressed={panel==='rf'}><RadioTower size={22}/><span>RF</span></button>
      <button className={panel==='ai-preview'?'is-panel-active':''} onClick={()=>onPanelChange('ai-preview')} title="AI Preview" aria-pressed={panel==='ai-preview'}><ScanEye size={22}/><span>AI Preview</span></button>
    </div>
    <div className="rail-tools">{tools.map((tool)=>{const Icon=tool.icon;return <button key={tool.id} className={active===tool.id?'is-active':''} onClick={()=>activate(tool.id)} title={tool.label}><Icon size={21}/><span>{tool.label}</span></button>})}</div>
    <div className="rail-state"><Wifi size={16}/><span>{connection}</span><small>USB 3</small></div>
    <MousePointer2 className="rail-cursor" size={12}/>
  </nav>
}
