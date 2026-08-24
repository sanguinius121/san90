import { useEffect, useRef, useState } from 'react'
import { aiReviewApi } from '../../data/aiReviewApi'
import type { AiReviewSaveStatus, AiReviewStatus } from '../../types/aiReview'
import { AiPowerRangeControl } from './AiPowerRangeControl'

const mhz = (hz: number) => (hz / 1e6).toFixed(3)

export function AiImagePreview() {
  const [status, setStatus] = useState<AiReviewStatus | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const [saveStatus, setSaveStatus] = useState<AiReviewSaveStatus | null>(null)
  const [savePending, setSavePending] = useState(false)
  const [saveRequestError, setSaveRequestError] = useState<string | null>(null)
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
        const next = await aiReviewApi.status(controller.signal)
        if (!mounted) return
        setStatus(next)
        setError(false)
        if (!next.available || next.sequence === null) {
          clearImage()
        } else if (next.sequence !== loadedSequence.current) {
          const expected = next.sequence
          let blob: Blob
          try {
            blob = await aiReviewApi.image(expected, controller.signal)
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

  useEffect(() => {
    let mounted = true
    let timer: number | null = null

    const poll = async () => {
      try {
        const next = await aiReviewApi.saveStatus()
        if (mounted) setSaveStatus(next)
      } catch {
        // Save-status polling failures are non-fatal; keep the last known state.
      } finally {
        if (mounted) timer = window.setTimeout(poll, document.hidden ? 2000 : 1000)
      }
    }

    void poll()
    return () => {
      mounted = false
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [])

  const toggleSave = async () => {
    setSavePending(true)
    setSaveRequestError(null)
    try {
      const next = saveStatus?.active ? await aiReviewApi.stopSave() : await aiReviewApi.startSave()
      setSaveStatus(next)
    } catch (cause) {
      setSaveRequestError(cause instanceof Error ? cause.message : 'Yêu cầu thất bại')
    } finally {
      setSavePending(false)
    }
  }

  const message = error
    ? 'Review unavailable'
    : 'Waiting for AI detection'

  const saving = saveStatus?.active ?? false
  const saveMessage = saveRequestError ?? saveStatus?.last_error ?? null

  return (
    <div className="ai-image-preview">
      <div className="ai-preview-actions">
        <button
          type="button"
          onClick={() => void toggleSave()}
          disabled={savePending}
          aria-pressed={saving}
        >
          {saving
            ? `Dừng lưu (${saveStatus?.saved_count ?? 0})`
            : 'Lưu kết quả'}
        </button>
        {saveMessage && <span className="ai-preview-save-error">{saveMessage}</span>}
      </div>
      <div className="ai-preview-frame">
        {imageUrl && status?.available
          ? <img src={imageUrl} alt="Latest AI detection" />
          : <span>{message}</span>}
      </div>
      <AiPowerRangeControl previewGeneration={status?.power_range_generation ?? null} />
      {status && (
        <div className="ai-preview-meta">
          <b>AI</b>
          {status.center_frequency_hz !== null && <span>Center {mhz(status.center_frequency_hz)} MHz</span>}
          {status.frequency_start_hz !== null && status.frequency_stop_hz !== null && (
            <span>{mhz(status.frequency_start_hz)}–{mhz(status.frequency_stop_hz)} MHz</span>
          )}
          {status.sequence !== null && <span>Frame {status.sequence}</span>}
          <span>{status.detection_count} detection{status.detection_count === 1 ? '' : 's'}</span>
        </div>
      )}
    </div>
  )
}
