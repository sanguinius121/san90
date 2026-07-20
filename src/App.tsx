import { useEffect } from 'react'
import { AppLayout } from './components/AppLayout'
import { MockSpectrumSource } from './data/mockSource'
import { WebSocketSpectrumSource } from './data/WebSocketSpectrumSource'
import './styles.css'

export default function App() {
  useEffect(()=>{
    const requested = new URLSearchParams(location.search).get('source') ?? import.meta.env.VITE_ANALYZER_SOURCE ?? 'simulator'
    const source = requested === 'san90'
      ? new WebSocketSpectrumSource(import.meta.env.VITE_ANALYZER_WS_URL ?? `ws://${location.hostname}:8000/ws/analyzer`)
      : new MockSpectrumSource()
    source.start(); return()=>source.stop()
  },[])
  return <AppLayout/>
}
