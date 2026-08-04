import { useDeviceStore, useRuntimeStore } from '../stores'
import { formatFrequency } from '../utils/format'

export function SpectrumStatusBar() {
  const centerHz = useDeviceStore((s) => s.centerHz); const spanHz = useDeviceStore((s) => s.spanHz)
  const rbw = useRuntimeStore((s) => s.actualRbwHz)
  const points = useRuntimeStore((s) => s.pointCount); const fft = useRuntimeStore((s) => s.fftSize)
  return <div className="spectrum-status">
    <span><i>CENTER</i>{formatFrequency(centerHz)}</span>
    <span><i>SPAN</i>{formatFrequency(spanHz)}</span>
    <span><i>SỐ ĐIỂM FFT</i>{fft ?? points}</span>
    <span><i>RBW</i>{formatFrequency(rbw)}</span>
  </div>
}
