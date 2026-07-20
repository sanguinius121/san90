import type { AxisGeometry } from './FrequencyAxis'
export function AmplitudeAxis(ctx: CanvasRenderingContext2D, area: AxisGeometry, minDbm: number, maxDbm: number) {
  ctx.save(); ctx.font = '11px Inter, system-ui, sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  for (let i = 0; i <= 10; i++) {
    const y = area.top + (area.bottom - area.top) * i / 10; const dbm = maxDbm - (maxDbm - minDbm) * i / 10
    ctx.strokeStyle = i === 5 ? '#334758' : '#21303b'; ctx.beginPath(); ctx.moveTo(area.left, y); ctx.lineTo(area.right, y); ctx.stroke()
    ctx.fillStyle = '#8ea1b0'; ctx.fillText(dbm.toFixed(0), area.left - 7, y)
  }
  ctx.restore()
}
