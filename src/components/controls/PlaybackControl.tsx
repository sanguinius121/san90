import { useCallback, useEffect, useRef, useState } from 'react'
import { playbackApi } from '../../data/playbackApi'
import { useRuntimeStore } from '../../stores'
import type { PlaybackState, PlaybackStatus, RecordingSummary } from '../../types/playback'

const BUSY = new Set<PlaybackState>(['opening', 'seeking', 'stopping'])
const OPEN = new Set<PlaybackState>(['ready', 'playing', 'paused', 'seeking', 'completed', 'failed'])

function clock(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const minutes = Math.floor(safe / 60)
  return `${String(minutes).padStart(2, '0')}:${(safe % 60).toFixed(1).padStart(4, '0')}`
}

function frequency(value: number | null): string {
  if (value == null) return '—'
  return value >= 1e9 ? `${Number((value / 1e9).toFixed(6))} GHz` : `${Number((value / 1e6).toFixed(3))} MHz`
}

const errorText = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback

export function PlaybackControl() {
  const [recordings, setRecordings] = useState<RecordingSummary[]>([])
  const [selected, setSelected] = useState('')
  const [status, setStatus] = useState<PlaybackStatus | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [requesting, setRequesting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draftPosition, setDraftPosition] = useState(0)
  const dragging = useRef(false)
  const draftRef = useRef(0)

  const applyStatus = useCallback((next: PlaybackStatus) => {
    setStatus(next)
    useRuntimeStore.getState().update({
      playbackActive: OPEN.has(next.state),
      playbackState: next.state,
    })
    if (!dragging.current) {
      draftRef.current = next.position_s
      setDraftPosition(next.position_s)
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoadingList(true)
    try {
      const items = (await playbackApi.recordings()).filter(item => item.playable && item.clean)
      setRecordings(items)
      setSelected(current =>
        current && items.some(item => item.id === current) ? current : (items[0]?.id ?? ''),
      )
      setError(null)
    } catch (cause) {
      setError(errorText(cause, 'Unable to list recordings'))
    } finally {
      setLoadingList(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    let mounted = true
    let timer: number | undefined
    const poll = async () => {
      let delay = 750
      try {
        const next = await playbackApi.status()
        if (!mounted) return
        applyStatus(next)
        delay = next.state === 'playing' || BUSY.has(next.state) ? 250 : 750
      } catch (cause) {
        if (mounted) setError(current => current ?? errorText(cause, 'Playback status unavailable'))
      }
      if (mounted) timer = window.setTimeout(poll, delay)
    }
    void poll()
    return () => {
      mounted = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [applyStatus])

  const command = async (operation: () => Promise<PlaybackStatus>) => {
    if (requesting) return
    setRequesting(true)
    setError(null)
    try {
      applyStatus(await operation())
    } catch (cause) {
      setError(errorText(cause, 'Playback request failed'))
    } finally {
      setRequesting(false)
    }
  }

  const seek = (position: number) => {
    const bounded = Math.min(status?.duration_s ?? 0, Math.max(0, position))
    void command(() => playbackApi.seek(bounded))
  }
  const commitTimeline = () => {
    if (!dragging.current) return
    dragging.current = false
    seek(draftRef.current)
  }
  const state = status?.state ?? 'idle'
  const opened = OPEN.has(state)
  const busy = requesting || BUSY.has(state)
  const canStep = opened && ['ready', 'paused', 'completed'].includes(state) && !busy
  const canSeek = opened && !busy
  const canPlay = ['ready', 'paused'].includes(state) && !busy
  const canPause = state === 'playing' && !busy
  const canStop = opened && state !== 'stopping' && !requesting

  return (
    <div className="playback-control">
      <div className="playback-picker">
        <select aria-label="Playback recording" value={selected} disabled={loadingList || opened}
          onChange={event => setSelected(event.target.value)}>
          {!recordings.length && <option value="">No playable recordings</option>}
          {recordings.map(item => <option value={item.id} key={item.id}>{item.filename} · {item.duration_s.toFixed(1)}s</option>)}
        </select>
        <button aria-label="Refresh recordings" disabled={loadingList || busy} onClick={() => void refresh()}>↻</button>
        <button aria-label="Open recording" disabled={!selected || opened || busy}
          onClick={() => void command(() => playbackApi.open(selected))}>Open</button>
      </div>
      <div className="playback-buttons">
        <button aria-label="Previous trace" disabled={!canStep} onClick={() => void command(() => playbackApi.step('previous'))}>|◀</button>
        <button aria-label="Back 5 seconds" disabled={!canSeek} onClick={() => seek((status?.position_s ?? 0) - 5)}>−5s</button>
        <button aria-label={state === 'playing' ? 'Pause playback' : 'Play playback'}
          disabled={state === 'playing' ? !canPause : !canPlay}
          onClick={() => void command(() => state === 'playing' ? playbackApi.pause() : playbackApi.play())}>
          {state === 'playing' ? '❚❚' : '▶'}
        </button>
        <button aria-label="Forward 5 seconds" disabled={!canSeek} onClick={() => seek((status?.position_s ?? 0) + 5)}>+5s</button>
        <button aria-label="Next trace" disabled={!canStep} onClick={() => void command(() => playbackApi.step('next'))}>▶|</button>
        <button aria-label="Stop playback" disabled={!canStop} onClick={() => void command(() => playbackApi.stop())}>■</button>
      </div>
      <div className="playback-time">{clock(dragging.current ? draftPosition : (status?.position_s ?? 0))} / {clock(status?.duration_s ?? 0)}</div>
      <input className="playback-timeline" aria-label="Playback timeline" type="range" min={0}
        max={Math.max(0, status?.duration_s ?? 0)} step="any" value={draftPosition}
        disabled={!canSeek}
        onPointerDown={() => { dragging.current = true }}
        onChange={event => { dragging.current = true; const value = Number(event.target.value); draftRef.current = value; setDraftPosition(value) }}
        onPointerUp={commitTimeline}
        onBlur={commitTimeline}
        onKeyUp={event => { if (event.key === 'Enter') { dragging.current = true; commitTimeline() } }} />
      <div className="playback-setting"><span>Auto Loop</span><button aria-pressed={status?.auto_loop ?? false}
        aria-label="Toggle Auto Loop"
        disabled={!opened || busy} onClick={() => void command(() => playbackApi.settings(!(status?.auto_loop ?? false), status?.run_ai ?? false))}>
        {status?.auto_loop ? 'On' : 'Off'}
      </button></div>
      <div className="playback-setting"><span>Run AI</span><button aria-pressed={status?.run_ai ?? false}
        aria-label="Toggle Run AI"
        disabled={!opened || busy} onClick={() => void command(() => playbackApi.settings(status?.auto_loop ?? false, !(status?.run_ai ?? false)))}>
        {status?.run_ai ? 'On' : 'Off'}
      </button></div>
      {opened && <div className="playback-meta">
        <span>{frequency(status?.center_frequency_hz ?? null)} · {status?.point_count?.toLocaleString() ?? '—'} points</span>
        <span>CONFIG {status?.current_config_id ?? '—'} · Pauses {status?.reconfiguration_pauses_passed ?? 0} · Lost {status?.lost_traces_passed ?? 0}</span>
        {(status?.loop_count ?? 0) > 0 && <span>Loops {status?.loop_count}</span>}
      </div>}
      {(error || status?.last_error || status?.ai_warning) &&
        <div className="record-error" role="status">{error ?? status?.last_error ?? status?.ai_warning}</div>}
    </div>
  )
}
