import type { AxisGeometry } from './FrequencyAxis'
import type { Marker } from '../types'
import { formatFrequency } from '../utils/format'
import { frequencyToPlotX } from '../rendering/plotGeometry'

export function MarkerOverlay(ctx: CanvasRenderingContext2D, area: AxisGeometry, marker: Marker | null, minDbm:number,maxDbm:number,startHz:number,stopHz:number) {
  if (!marker) return
  if(marker.frequencyHz<startHz||marker.frequencyHz>stopHz)return
  const x=frequencyToPlotX(marker.frequencyHz,startHz,stopHz,{left:area.left,right:area.right,width:area.right-area.left})
  const y = area.bottom - (marker.amplitudeDbm - minDbm) / (maxDbm - minDbm) * (area.bottom - area.top)
  ctx.save(); ctx.strokeStyle = '#31d8ff'; ctx.fillStyle = '#31d8ff'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 6, y - 10); ctx.lineTo(x + 6, y - 10); ctx.closePath(); ctx.fill()
  const label = `M1  ${formatFrequency(marker.frequencyHz, 6)}   ${marker.amplitudeDbm.toFixed(1)} dBm`
  ctx.font = '600 11px Inter, system-ui'; const width = ctx.measureText(label).width + 16; const lx = Math.min(x + 8, area.right - width)
  ctx.fillStyle = '#06131a'; ctx.fillRect(lx, area.top + 8, width, 23); ctx.strokeStyle = '#269bb8'; ctx.strokeRect(lx + .5, area.top + 8.5, width - 1, 22)
  ctx.fillStyle = '#64e4ff'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(label, lx + 8, area.top + 20)
  ctx.restore()
}
