import { useEffect, useRef, useState } from 'react'
import { aiPreviewApi } from '../../data/aiPreviewApi'
import type { AiPreviewStatus } from '../../types/aiPreview'

const sourceLabel = (source: string) => source.toUpperCase()
const mhz = (hz: number) => (hz / 1e6).toFixed(3)

export function AiImagePreview() {
  const [status, setStatus] = useState<AiPreviewStatus | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const loadedSequence = useRef<number | null>(null)
  const objectUrl = useRef<string | null>(null)

  useEffect(() => {
    let mounted = true
    let timer: number | null = null
    let controller: AbortController | null = null

    const clearImage = () => {
      loadedSequence.current = null
      if (objectUrl.current !== null) {
        URL.revokeObjectURL(objectUrl.current)
        objectUrl.current = null
      }
      if (mounted) setImageUrl(null)
    }

    const poll = async () => {
      controller = new AbortController()
      try {
        // A hidden tab still checks status slowly, but does not renew the
        // encoder lease. Encoding therefore stops after the short backend TTL.
        const next = await aiPreviewApi.status(controller.signal, !document.hidden)
        if (!mounted) return
        setStatus(next)
        setError(false)
        if (!next.available || next.sequence === null) {
          clearImage()
        } else if (next.sequence !== loadedSequence.current) {
          const expected = next.sequence
          let blob: Blob
          try {
            blob = await aiPreviewApi.image(expected, controller.signal)
          } catch (cause) {
            if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
            // The latest-only backend may advance between status and image.
            // Keep the prior image and retry from fresh status on the next tick.
            return
          }
          if (!mounted) return
          const nextUrl = URL.createObjectURL(blob)
          if (objectUrl.current !== null) URL.revokeObjectURL(objectUrl.current)
          objectUrl.current = nextUrl
          loadedSequence.current = expected
          setImageUrl(nextUrl)
        }
      } catch (cause) {
        if (!mounted || (cause instanceof DOMException && cause.name === 'AbortError')) return
        clearImage()
        setError(true)
      } finally {
        if (mounted) timer = window.setTimeout(poll, document.hidden ? 1000 : 250)
      }
    }

    void poll()
    return () => {
      mounted = false
      controller?.abort()
      if (timer !== null) window.clearTimeout(timer)
      if (objectUrl.current !== null) URL.revokeObjectURL(objectUrl.current)
      objectUrl.current = null
    }
  }, [])

  const message = error
    ? 'Preview unavailable'
    : status?.reason === 'playback_ai_disabled'
      ? 'AI preview disabled for playback'
      : 'Waiting for AI image'

  return (
    <div className="ai-image-preview">
      <div className="ai-preview-frame">
        {imageUrl && status?.available
          ? <img src={imageUrl} alt="Latest AI input" />
          : <span>{message}</span>}
      </div>
      {status && (
        <div className="ai-preview-meta">
          <b>{sourceLabel(status.source)}</b>
          {status.center_frequency_hz !== null && <span>Center {mhz(status.center_frequency_hz)} MHz</span>}
          {status.frequency_start_hz !== null && status.frequency_stop_hz !== null && (
            <span>{mhz(status.frequency_start_hz)}–{mhz(status.frequency_stop_hz)} MHz</span>
          )}
          {status.sequence !== null && <span title={status.playback_epoch === null ? undefined : `Playback epoch ${status.playback_epoch}`}>Frame {status.sequence}</span>}
        </div>
      )}
    </div>
  )
}
