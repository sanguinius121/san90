import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent } from 'react'
import { aiPowerRangeApi } from '../../data/aiPowerRangeApi'
import type { AiPowerPreset, AiPowerRange } from '../../types/aiPowerRange'

const PRESETS: Record<AiPowerPreset, { label: string; low: number; high: number }> = {
  normal: { label: 'Normal', low: -130, high: -50 },
  external_lna: { label: 'Ext. LNA', low: -120, high: -20 },
  strong_signal: { label: 'Strong', low: -100, high: 0 },
}

interface Props {
  previewGeneration: number | null
}

export function AiPowerRangeControl({ previewGeneration }: Props) {
  const [verified, setVerified] = useState<AiPowerRange | null>(null)
  const [draftLow, setDraftLow] = useState(-120)
  const [draftHigh, setDraftHigh] = useState(-20)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [awaitingGeneration, setAwaitingGeneration] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const draftRef = useRef({ low: -120, high: -20 })
  const editingRef = useRef(false)
  const savingRef = useRef(false)

  const accept = useCallback((next: AiPowerRange, forceDraft = false) => {
    setVerified(next)
    if (forceDraft || (!editingRef.current && !savingRef.current)) {
      draftRef.current = { low: next.power_min_dbm, high: next.power_max_dbm }
      setDraftLow(next.power_min_dbm)
      setDraftHigh(next.power_max_dbm)
    }
  }, [])

  useEffect(() => {
    let mounted = true
    let timer: number | null = null
    let controller: AbortController | null = null
    const poll = async () => {
      controller = new AbortController()
      try {
        const next = await aiPowerRangeApi.get(controller.signal)
        if (mounted) accept(next)
      } catch (cause) {
        if (mounted && !(cause instanceof DOMException && cause.name === 'AbortError')) {
          setError('Power range unavailable')
        }
      } finally {
        if (mounted) timer = window.setTimeout(poll, 1000)
      }
    }
    void poll()
    return () => {
      mounted = false
      controller?.abort()
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [accept])

  useEffect(() => {
    if (awaitingGeneration !== null && previewGeneration === awaitingGeneration) {
      setAwaitingGeneration(null)
    }
  }, [awaitingGeneration, previewGeneration])

  const setDraft = (low: number, high: number) => {
    draftRef.current = { low, high }
    setDraftLow(low)
    setDraftHigh(high)
  }

  const commit = useCallback(async (low = draftRef.current.low, high = draftRef.current.high) => {
    editingRef.current = false
    setEditing(false)
    if (verified && low === verified.power_min_dbm && high === verified.power_max_dbm) return
    setSaving(true)
    savingRef.current = true
    setError(null)
    try {
      const next = await aiPowerRangeApi.update(low, high)
      accept(next, true)
      setAwaitingGeneration(next.generation)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Power range update failed')
      if (verified) setDraft(verified.power_min_dbm, verified.power_max_dbm)
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }, [accept, verified])

  const beginEdit = () => {
    editingRef.current = true
    setEditing(true)
  }
  const shiftKeyAdjust = (handle: 'low' | 'high', event: KeyboardEvent<HTMLInputElement>) => {
    if (!event.shiftKey || !event.key.startsWith('Arrow')) return
    event.preventDefault()
    const direction = event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -1 : 1
    beginEdit()
    if (handle === 'low') {
      setDraft(Math.max(min, Math.min(draftLow + direction * 5, draftHigh - gap)), draftHigh)
    } else {
      setDraft(draftLow, Math.min(max, Math.max(draftHigh + direction * 5, draftLow + gap)))
    }
  }
  const min = verified?.supported_min_dbm ?? -140
  const max = verified?.supported_max_dbm ?? 10
  const gap = verified?.minimum_range_db ?? 10
  const lowPercent = ((draftLow - min) / (max - min)) * 100
  const highPercent = ((draftHigh - min) / (max - min)) * 100
  const draftPreset = (Object.entries(PRESETS) as [AiPowerPreset, typeof PRESETS[AiPowerPreset]][])
    .find(([, value]) => value.low === draftLow && value.high === draftHigh)?.[0] ?? null
  const applying = saving || awaitingGeneration !== null

  return (
    <section className="ai-power-range" aria-label="GRAY8 Power Range">
      <div className="ai-power-range-title">
        <b>GRAY8 POWER RANGE</b>
        <span>{editing ? 'CUSTOM' : applying ? 'APPLYING…' : verified?.preset?.replace('_', ' ').toUpperCase() ?? 'CUSTOM'}</span>
      </div>
      <div className="ai-range-limits"><span>{min} dBm</span><span>+{max} dBm</span></div>
      <div
        className="ai-range-track"
        style={{ '--range-low': `${lowPercent}%`, '--range-high': `${highPercent}%` } as CSSProperties}
      >
        <input
          aria-label="Lower power threshold"
          type="range" min={min} max={max - gap} step={1} value={draftLow}
          onPointerDown={beginEdit}
          onChange={event => { beginEdit(); setDraft(Math.min(Number(event.target.value), draftHigh - gap), draftHigh) }}
          onPointerUp={() => void commit()}
          onPointerCancel={() => { editingRef.current = false; setEditing(false); if (verified) setDraft(verified.power_min_dbm, verified.power_max_dbm) }}
          onKeyDown={event => shiftKeyAdjust('low', event)}
          onKeyUp={event => { if (event.key.startsWith('Arrow') || event.key === 'Home' || event.key === 'End') void commit() }}
          aria-valuetext={`${draftLow} dBm`}
        />
        <input
          aria-label="Upper power threshold"
          type="range" min={min + gap} max={max} step={1} value={draftHigh}
          onPointerDown={beginEdit}
          onChange={event => { beginEdit(); setDraft(draftLow, Math.max(Number(event.target.value), draftLow + gap)) }}
          onPointerUp={() => void commit()}
          onPointerCancel={() => { editingRef.current = false; setEditing(false); if (verified) setDraft(verified.power_min_dbm, verified.power_max_dbm) }}
          onKeyDown={event => shiftKeyAdjust('high', event)}
          onKeyUp={event => { if (event.key.startsWith('Arrow') || event.key === 'Home' || event.key === 'End') void commit() }}
          aria-valuetext={`${draftHigh} dBm`}
        />
      </div>
      <div className="ai-range-values">
        <span>Low</span><b>{draftLow} dBm</b>
        <span>High</span><b>{draftHigh} dBm</b>
        <span>Range</span><b>{draftHigh - draftLow} dB</b>
        <span>Resolution</span><b>{((draftHigh - draftLow) / 255).toFixed(3)} dB/level</b>
      </div>
      <div className="ai-range-presets">
        {(Object.entries(PRESETS) as [AiPowerPreset, typeof PRESETS[AiPowerPreset]][]).map(([name, preset]) => (
          <button
            key={name} type="button" aria-pressed={draftPreset === name} disabled={saving}
            onClick={() => { setDraft(preset.low, preset.high); void commit(preset.low, preset.high) }}
          >{preset.label}</button>
        ))}
      </div>
      {error && <span className="ai-power-range-error">{error}</span>}
    </section>
  )
}
