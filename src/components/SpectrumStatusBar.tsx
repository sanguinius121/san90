import { useDeviceStore, useRuntimeStore } from '../stores'
import { formatFrequency } from '../utils/format'

export function SpectrumStatusBar() {
  const centerHz = useDeviceStore((s) => s.centerHz); const spanHz = useDeviceStore((s) => s.spanHz)
  const rbw = useRuntimeStore((s) => s.actualRbwHz); const fps = useRuntimeStore((s) => s.fps)
  const points = useRuntimeStore((s) => s.pointCount); const fft = useRuntimeStore((s) => s.fftSize); const binSpacing = useRuntimeStore((s) => s.frequencyBinSpacingHz)
  const window = useDeviceStore((s) => s.window); const detector = useDeviceStore((s) => s.detector)
  return <div className="spectrum-status">
    <span><i>START</i>{formatFrequency(centerHz - spanHz / 2)}</span><span><i>CENTER</i>{formatFrequency(centerHz)}</span>
    <span><i>SPAN</i>{formatFrequency(spanHz)}</span><span><i>RBW</i>{formatFrequency(rbw)}</span><span><i>PTS / FFT</i>{points}{fft ? ` / ${fft}` : ''}</span>
    {binSpacing != null && <span><i>BIN</i>{formatFrequency(binSpacing)}</span>}
    <span><i>WINDOW</i>{labels(window)}</span><span><i>DETECT</i>{labels(detector)}</span><span><i>RATE</i>{fps} FPS</span>
  </div>
}

const labels=(value:string)=>value.replaceAll('-', ' ').toUpperCase()
