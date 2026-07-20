export const SHARED_PLOT_LEFT_CSS_PX = 48
export const SHARED_PLOT_RIGHT_GUTTER_CSS_PX = 10

export interface HorizontalPlotRect {
  left: number
  right: number
  width: number
}

export function sharedHorizontalPlotRect(canvasCssWidth: number): HorizontalPlotRect {
  if (!Number.isFinite(canvasCssWidth) || canvasCssWidth <= 0) throw new Error('Canvas CSS width must be positive')
  const left = Math.min(SHARED_PLOT_LEFT_CSS_PX, Math.max(0, canvasCssWidth - 1))
  const right = Math.max(left + 1, canvasCssWidth - SHARED_PLOT_RIGHT_GUTTER_CSS_PX)
  return { left, right, width: right - left }
}

export function plotRectFramebuffer(canvasCssWidth: number, framebufferWidth: number): HorizontalPlotRect {
  if (!Number.isFinite(framebufferWidth) || framebufferWidth <= 0) throw new Error('Framebuffer width must be positive')
  const css = sharedHorizontalPlotRect(canvasCssWidth)
  const scale = framebufferWidth / canvasCssWidth
  const left = Math.round(css.left * scale)
  const right = Math.round(css.right * scale)
  return { left, right, width: Math.max(1, right - left) }
}

export function frequencyToPlotX(frequencyHz: number, startHz: number, stopHz: number, rect: HorizontalPlotRect): number {
  if (![frequencyHz, startHz, stopHz].every(Number.isFinite) || stopHz <= startHz) throw new Error('Frequency axis is invalid')
  return rect.left + (frequencyHz - startHz) / (stopHz - startHz) * rect.width
}

export function plotXToNormalizedFrequency(x: number, rect: HorizontalPlotRect): number {
  return Math.max(0, Math.min(1, (x - rect.left) / rect.width))
}
