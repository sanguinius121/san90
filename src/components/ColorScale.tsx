import { useRuntimeStore } from '../stores'

export function ColorScale() {
  const floor=useRuntimeStore((state)=>state.waterfallFloorDbm); const ceiling=useRuntimeStore((state)=>state.waterfallCeilingDbm)
  return <div className="color-scale" aria-label="Spectrogram color scale">
    <span>{floor.toFixed(0)}</span><div className="color-scale__bar"/><span>{ceiling.toFixed(0)} dBm</span>
  </div>
}
