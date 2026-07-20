import { shortFrequency } from '../utils/format'

export interface AxisGeometry { left: number; right: number; top: number; bottom: number }
export function FrequencyAxis(ctx: CanvasRenderingContext2D, area: AxisGeometry, startHz: number, stopHz: number) {
  ctx.save(); ctx.font = '11px Inter, system-ui, sans-serif'; ctx.fillStyle = '#8ea1b0'; ctx.textBaseline = 'top'
  for (let i = 0; i <= 8; i++) {
    const x = area.left + (area.right - area.left) * i / 8
    ctx.strokeStyle = i === 4 ? '#334758' : '#21303b'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke()
    const label = shortFrequency(startHz + (stopHz - startHz) * i / 8); ctx.textAlign = i === 0 ? 'left' : i === 8 ? 'right' : 'center'; ctx.fillText(label, x, area.bottom + 5)
  }
  ctx.restore()
}
