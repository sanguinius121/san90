import type { AxisGeometry } from './FrequencyAxis'
import { spectrumAmplitudeTicks } from '../rendering/amplitudeScale'
export function AmplitudeAxis(ctx: CanvasRenderingContext2D, area: AxisGeometry, minDbm: number, maxDbm: number) {
  ctx.save(); ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  const ticks = spectrumAmplitudeTicks({ minDbm, maxDbm })
  for (let i = 0; i < ticks.length; i++) {
    const y = area.top + (area.bottom - area.top) * i / (ticks.length - 1); const dbm = ticks[i]
    ctx.strokeStyle = i === 5 ? '#334758' : '#21303b'; ctx.beginPath(); ctx.moveTo(area.left, y); ctx.lineTo(area.right, y); ctx.stroke()
    ctx.fillStyle = '#8ea1b0'; ctx.fillText(dbm.toFixed(0), area.left - 7, y)
  }
  ctx.restore()
}
