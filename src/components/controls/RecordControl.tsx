import { useCallback, useEffect, useRef, useState } from 'react'
import { recordingApi } from '../../data/recordingApi'
import {
  bytesToUnit,
  cleanNumber,
  formatBytes,
  formatElapsed,
  MIN_RECORDING_FILE_BYTES,
  RECORDING_STOP_REASON_LABELS,
  recordingFilename,
  unitToBytes,
  validRecordingPrefix,
  validRelativeRecordingDirectory,
  type RecordingByteUnit,
} from '../../data/recordingFormat'
import type {
  RecordingConfig,
  RecordingConfigUpdate,
  RecordingMode,
  RecordingState,
  RecordingStatus,
} from '../../types/recording'
import { useRfSidebarLocalization } from '../../data/rfSidebarLocalization'

const ACTIVE_STATES: ReadonlySet<RecordingState> = new Set([
  'starting',
  'recording',
  'stopping',
  'finalizing',
])

interface RecordingDrafts {
  mode: RecordingMode
  duration: string
  fileSize: string
  fileSizeUnit: RecordingByteUnit
  reserve: string
  reserveUnit: RecordingByteUnit
  outputDirectory: string
  filePrefix: string
}

const defaultDrafts: RecordingDrafts = {
  mode: 'fixed',
  duration: '5.0',
  fileSize: '4',
  fileSizeUnit: 'GB',
  reserve: '2',
  reserveUnit: 'GB',
  outputDirectory: '.',
  filePrefix: 'SAN90_RTA',
}

function durationDraft(value: number | null): string {
  if (value == null) return '5.0'
  return Number.isInteger(value) ? value.toFixed(1) : cleanNumber(value, 6)
}

function preferredByteUnit(bytes: number): RecordingByteUnit {
  return bytes >= 1024 ** 3 ? 'GB' : 'MB'
}

function draftsFromConfig(config: RecordingConfig): RecordingDrafts {
  const fileSizeUnit = preferredByteUnit(config.file_size_limit_bytes)
  const reserveUnit = preferredByteUnit(config.free_disk_reserve_bytes)
  return {
    mode: config.mode,
    duration: durationDraft(config.duration_s),
    fileSize: cleanNumber(bytesToUnit(config.file_size_limit_bytes, fileSizeUnit), 6),
    fileSizeUnit,
    reserve: cleanNumber(bytesToUnit(config.free_disk_reserve_bytes, reserveUnit), 6),
    reserveUnit,
    outputDirectory: config.output_directory,
    filePrefix: config.file_prefix,
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function validateDrafts(drafts: RecordingDrafts): RecordingConfigUpdate | string {
  const duration = Number(drafts.duration)
  if (
    drafts.mode === 'fixed' &&
    (!drafts.duration.trim() || !Number.isFinite(duration) || duration <= 0)
  ) {
    return 'Record time must be a finite positive number of seconds.'
  }
  const fileSize = Number(drafts.fileSize)
  const fileSizeBytes = unitToBytes(fileSize, drafts.fileSizeUnit)
  if (
    !drafts.fileSize.trim() ||
    !Number.isFinite(fileSize) ||
    fileSize <= 0 ||
    !Number.isSafeInteger(fileSizeBytes) ||
    fileSizeBytes < MIN_RECORDING_FILE_BYTES
  ) {
    return 'File size limit must be positive and at least 16 KiB.'
  }
  const reserve = Number(drafts.reserve)
  const reserveBytes = unitToBytes(reserve, drafts.reserveUnit)
  if (
    !drafts.reserve.trim() ||
    !Number.isFinite(reserve) ||
    reserve < 0 ||
    !Number.isSafeInteger(reserveBytes)
  ) {
    return 'Disk reserve must be a finite non-negative value.'
  }
  const outputDirectory = drafts.outputDirectory.trim() || '.'
  if (!validRelativeRecordingDirectory(outputDirectory)) {
    return 'Output directory must be relative to the recording root and cannot contain "..".'
  }
  if (!validRecordingPrefix(drafts.filePrefix)) {
    return 'Prefix must use 1–64 letters, digits, ".", "_" or "-", without "..".'
  }
  return {
    mode: drafts.mode,
    duration_s: drafts.mode === 'fixed' ? duration : null,
    file_size_limit_bytes: fileSizeBytes,
    free_disk_reserve_bytes: reserveBytes,
    output_directory: outputDirectory,
    file_prefix: drafts.filePrefix,
  }
}

function stateLabel(state: RecordingState): string {
  return state.toUpperCase()
}

export function RecordControl({ disabled = false }: { disabled?: boolean }) {
  const text=useRfSidebarLocalization('Record')
  const common=useRfSidebarLocalization('Common')
  const [config, setConfig] = useState<RecordingConfig | null>(null)
  const [drafts, setDraftState] = useState<RecordingDrafts>(defaultDrafts)
  const draftsRef = useRef(drafts)
  const configInitialized = useRef(false)
  const editing = useRef(new Set<keyof RecordingDrafts>())
  const saveSequence = useRef(0)
  const [status, setStatus] = useState<RecordingStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const [requestTransition, setRequestTransition] = useState<'starting' | 'stopping' | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [directories, setDirectories] = useState<string[]>([])
  const [directoryRootName, setDirectoryRootName] = useState('SAN90_Recordings')
  const [newDirectory, setNewDirectory] = useState('')
  const [directoryLoading, setDirectoryLoading] = useState(false)
  const [directoryError, setDirectoryError] = useState<string | null>(null)
  const startPending = useRef(false)
  const stopIssued = useRef(false)

  const setDrafts = useCallback((
    update: Partial<RecordingDrafts> | ((current: RecordingDrafts) => RecordingDrafts),
  ) => {
    const next =
      typeof update === 'function'
        ? update(draftsRef.current)
        : { ...draftsRef.current, ...update }
    draftsRef.current = next
    setDraftState(next)
  }, [])

  const applyVerifiedConfig = useCallback((verified: RecordingConfig) => {
    setConfig(verified)
    const normalized = draftsFromConfig(verified)
    if (configInitialized.current) {
      normalized.fileSizeUnit = draftsRef.current.fileSizeUnit
      normalized.fileSize = cleanNumber(
        bytesToUnit(verified.file_size_limit_bytes, normalized.fileSizeUnit),
        6,
      )
      normalized.reserveUnit = draftsRef.current.reserveUnit
      normalized.reserve = cleanNumber(
        bytesToUnit(verified.free_disk_reserve_bytes, normalized.reserveUnit),
        6,
      )
    }
    configInitialized.current = true
    const next = { ...draftsRef.current }
    for (const key of Object.keys(normalized) as (keyof RecordingDrafts)[]) {
      if (!editing.current.has(key)) {
        ;(next as Record<keyof RecordingDrafts, string>)[key] = normalized[key]
      }
    }
    setDrafts(next)
  }, [setDrafts])

  useEffect(() => {
    let mounted = true
    void recordingApi
      .config()
      .then(verified => {
        if (!mounted) return
        applyVerifiedConfig(verified)
        setRequestError(verified.load_warning ?? verified.save_error)
      })
      .catch(error => {
        if (mounted) setRequestError(errorMessage(error, 'Unable to load recording configuration'))
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [applyVerifiedConfig])

  useEffect(() => {
    let mounted = true
    let timer: number | undefined
    const poll = async () => {
      let delay = 750
      try {
        const next = await recordingApi.status()
        if (!mounted) return
        setStatus(next)
        setPollError(null)
        delay = ACTIVE_STATES.has(next.state) ? 250 : 750
        if (next.state === 'recording' || next.state === 'starting') stopIssued.current = false
      } catch (error) {
        if (!mounted) return
        setPollError(current =>
          current ?? errorMessage(error, 'Recording status is temporarily unavailable'),
        )
      }
      if (mounted) timer = window.setTimeout(poll, delay)
    }
    void poll()
    return () => {
      mounted = false
      window.clearTimeout(timer)
    }
  }, [])

  const commitDrafts = async (
    overrides: Partial<RecordingDrafts> = {},
  ): Promise<RecordingConfig | null> => {
    const next = { ...draftsRef.current, ...overrides }
    setDrafts(next)
    const validated = validateDrafts(next)
    if (typeof validated === 'string') {
      setRequestError(validated)
      return null
    }
    const sequence = ++saveSequence.current
    setSaving(true)
    setRequestError(null)
    try {
      const verified = await recordingApi.updateConfig(validated)
      if (sequence === saveSequence.current) applyVerifiedConfig(verified)
      return verified
    } catch (error) {
      if (sequence === saveSequence.current) {
        setRequestError(errorMessage(error, 'Unable to save recording configuration'))
      }
      return null
    } finally {
      if (sequence === saveSequence.current) setSaving(false)
    }
  }

  const commitField = (field: keyof RecordingDrafts) => {
    editing.current.delete(field)
    void commitDrafts()
  }

  const restoreField = (field: keyof RecordingDrafts) => {
    editing.current.delete(field)
    if (!config) return
    const normalized = draftsFromConfig(config)
    if (field === 'fileSize') {
      normalized.fileSize = cleanNumber(
        bytesToUnit(config.file_size_limit_bytes, draftsRef.current.fileSizeUnit),
        6,
      )
    } else if (field === 'reserve') {
      normalized.reserve = cleanNumber(
        bytesToUnit(config.free_disk_reserve_bytes, draftsRef.current.reserveUnit),
        6,
      )
    }
    setDrafts({ [field]: normalized[field] })
  }

  const adjustNumber = (
    field: 'duration' | 'fileSize' | 'reserve',
    amount: number,
  ) => {
    const current = Number(draftsRef.current[field])
    if (!Number.isFinite(current)) {
      setRequestError(`Enter a valid ${field === 'duration' ? 'record time' : 'storage value'} first.`)
      return
    }
    const minimum = field === 'reserve' ? 0 : Number.MIN_VALUE
    const value = Math.max(minimum, current + amount)
    editing.current.delete(field)
    void commitDrafts({ [field]: cleanNumber(value, 6) })
  }

  const changeByteUnit = (
    field: 'fileSize' | 'reserve',
    unitField: 'fileSizeUnit' | 'reserveUnit',
    nextUnit: RecordingByteUnit,
  ) => {
    const currentUnit = draftsRef.current[unitField]
    if (currentUnit === nextUnit) return
    const parsed = Number(draftsRef.current[field])
    const fallbackBytes =
      field === 'fileSize'
        ? config?.file_size_limit_bytes
        : config?.free_disk_reserve_bytes
    const bytes =
      draftsRef.current[field].trim() && Number.isFinite(parsed)
        ? unitToBytes(parsed, currentUnit)
        : (fallbackBytes ?? 0)
    editing.current.delete(field)
    const nextDraft = cleanNumber(bytesToUnit(bytes, nextUnit), 6)
    void commitDrafts({ [field]: nextDraft, [unitField]: nextUnit })
  }

  const start = async () => {
    if (startPending.current || (status && ACTIVE_STATES.has(status.state))) return
    startPending.current = true
    stopIssued.current = false
    setRequestError(null)
    try {
      const verified = await commitDrafts()
      if (!verified) return
      setRequestTransition('starting')
      setStatus(await recordingApi.start())
    } catch (error) {
      setRequestError(errorMessage(error, 'Unable to start recording'))
    } finally {
      setRequestTransition(null)
      startPending.current = false
    }
  }

  const stop = async () => {
    if (stopIssued.current || !status || !ACTIVE_STATES.has(status.state)) return
    stopIssued.current = true
    setRequestError(null)
    setRequestTransition('stopping')
    try {
      setStatus(await recordingApi.stop())
    } catch (error) {
      stopIssued.current = false
      setRequestError(errorMessage(error, 'Unable to stop recording'))
    } finally {
      setRequestTransition(null)
    }
  }

  const openDirectoryPicker = async () => {
    setPickerOpen(true)
    setDirectoryLoading(true)
    setDirectoryError(null)
    try {
      const result = await recordingApi.directories()
      setDirectories(result.directories)
      setDirectoryRootName(result.root_name)
    } catch (error) {
      setDirectoryError(errorMessage(error, 'Unable to list recording directories'))
    } finally {
      setDirectoryLoading(false)
    }
  }

  const chooseDirectory = async (directory: string) => {
    editing.current.delete('outputDirectory')
    const verified = await commitDrafts({ outputDirectory: directory })
    if (verified) setPickerOpen(false)
  }

  const createDirectory = async () => {
    const candidate = newDirectory.trim()
    if (!candidate || candidate === '.' || !validRelativeRecordingDirectory(candidate)) {
      setDirectoryError('Enter a safe relative directory below the recording root.')
      return
    }
    setDirectoryLoading(true)
    setDirectoryError(null)
    try {
      const result = await recordingApi.createDirectory(candidate)
      setDirectories(result.directories)
      setDirectoryRootName(result.root_name)
      setNewDirectory('')
      if (result.created) await chooseDirectory(result.created)
    } catch (error) {
      setDirectoryError(errorMessage(error, 'Unable to create recording directory'))
    } finally {
      setDirectoryLoading(false)
    }
  }

  const state = requestTransition ?? status?.state ?? 'idle'
  const active = ACTIVE_STATES.has(state)
  const controlsDisabled = disabled || loading || saving || active
  const fileName = recordingFilename(status?.final_file_path ?? status?.part_file_path ?? null)
  const targetDuration =
    (status?.mode ?? drafts.mode) === 'fixed' ? Number(drafts.duration) : null
  const queueRatio = Math.max(
    status?.queue_fill_ratio ?? 0,
    status?.queue_item_fill_ratio ?? 0,
  )
  const warning =
    state === 'failed' ||
    queueRatio >= 0.7 ||
    (status?.rejected_batches ?? 0) > 0 ||
    (status?.gap_count ?? 0) > 0 ||
    (status?.lost_trace_count ?? 0) > 0
  const diskNearReserve =
    status?.available_disk_bytes != null &&
    config != null &&
    status.available_disk_bytes <= config.free_disk_reserve_bytes * 1.2
  const reason = status?.stop_reason
    ? RECORDING_STOP_REASON_LABELS[status.stop_reason]
    : null

  const textField = (
    field: 'outputDirectory' | 'filePrefix',
    label: string,
    title?: string,
  ) => (
    <div className={`control-row ${controlsDisabled ? 'is-disabled' : ''}`}>
      <label htmlFor={`recording-${field}`}>{label}</label>
      <input
        id={`recording-${field}`}
        className="record-text-input"
        aria-label={label}
        title={title}
        disabled={controlsDisabled}
        value={drafts[field]}
        onFocus={() => editing.current.add(field)}
        onChange={event => {
          editing.current.add(field)
          setDrafts({ [field]: event.target.value })
        }}
        onBlur={() => commitField(field)}
        onKeyDown={event => {
          if (event.key === 'Enter') commitField(field)
          if (event.key === 'Escape') {
            restoreField(field)
          }
        }}
      />
    </div>
  )

  const byteField = (
    field: 'fileSize' | 'reserve',
    unitField: 'fileSizeUnit' | 'reserveUnit',
    label: string,
    step: number,
  ) => (
    <div className={`control-row ${controlsDisabled ? 'is-disabled' : ''}`}>
      <label htmlFor={`recording-${field}`}>{label}</label>
      <div className="record-byte-control">
        <span>
          <input
            id={`recording-${field}`}
            aria-label={label}
            disabled={controlsDisabled}
            inputMode="decimal"
            value={drafts[field]}
            onFocus={() => editing.current.add(field)}
            onChange={event => {
              editing.current.add(field)
              setDrafts({ [field]: event.target.value })
            }}
            onBlur={() => commitField(field)}
            onKeyDown={event => {
              if (event.key === 'Enter') commitField(field)
              if (event.key === 'Escape' && config) {
                restoreField(field)
              }
            }}
          />
          <select
            aria-label={`${label} unit`}
            title={text.language==='en'?'Binary conversion: MB = 1,048,576 bytes; GB = 1,073,741,824 bytes':text.hint('Binary conversion: MB = 1,048,576 bytes; GB = 1,073,741,824 bytes')}
            disabled={controlsDisabled}
            value={drafts[unitField]}
            onChange={event =>
              changeByteUnit(field, unitField, event.target.value as RecordingByteUnit)
            }
          >
            <option value="MB">MB</option>
            <option value="GB">GB</option>
          </select>
        </span>
        <button
          aria-label={common.t('Decrease {control label}',{'control label':label})}
          disabled={controlsDisabled}
          onClick={() => adjustNumber(field, -step)}
        >
          −
        </button>
        <button
          aria-label={common.t('Increase {control label}',{'control label':label})}
          disabled={controlsDisabled}
          onClick={() => adjustNumber(field, step)}
        >
          +
        </button>
      </div>
    </div>
  )

  return (
    <div className="record-control">
      <div className="control-row">
        <label>{text.t('Record')}</label>
        <div className="record-switch" role="group" aria-label={text.t('Record')}>
          <button
            aria-label={text.t('Start recording')}
            aria-pressed={active}
            disabled={disabled || active || loading || saving}
            onClick={() => void start()}
          >
            {text.t('On')}
          </button>
          <button
            aria-label={text.t('Stop recording')}
            aria-pressed={!active}
            disabled={!active}
            onClick={() => void stop()}
          >
            {text.t('Off')}
          </button>
        </div>
      </div>

      <div className={`control-row ${controlsDisabled ? 'is-disabled' : ''}`}>
        <label htmlFor="recording-mode">{text.t('Record mode')}</label>
        <select
          id="recording-mode"
          aria-label={text.t('Record mode')}
          disabled={controlsDisabled}
          value={drafts.mode}
          onChange={event => {
            const mode = event.target.value as RecordingMode
            void commitDrafts({ mode })
          }}
        >
          <option value="fixed">{text.t('Fixed')}</option>
          <option value="manual">{text.t('Manual')}</option>
        </select>
      </div>

      <div className={`control-row ${controlsDisabled || drafts.mode === 'manual' ? 'is-disabled' : ''}`}>
        <label htmlFor="recording-duration">{text.t('Record time')}</label>
        <div className="record-byte-control">
          <span>
            <input
              id="recording-duration"
              aria-label={text.t('Record time')}
              disabled={controlsDisabled || drafts.mode === 'manual'}
              inputMode="decimal"
              value={drafts.duration}
              onFocus={() => editing.current.add('duration')}
              onChange={event => {
                editing.current.add('duration')
                setDrafts({ duration: event.target.value })
              }}
              onBlur={() => commitField('duration')}
              onKeyDown={event => {
                if (event.key === 'Enter') commitField('duration')
                if (event.key === 'Escape' && config) {
                  restoreField('duration')
                }
              }}
            />
            <em>s</em>
          </span>
          <button
            aria-label={common.t('Decrease {control label}',{'control label':text.t('Record time')})}
            disabled={controlsDisabled || drafts.mode === 'manual'}
            onClick={() => adjustNumber('duration', -1)}
          >
            −
          </button>
          <button
            aria-label={common.t('Increase {control label}',{'control label':text.t('Record time')})}
            disabled={controlsDisabled || drafts.mode === 'manual'}
            onClick={() => adjustNumber('duration', 1)}
          >
            +
          </button>
        </div>
      </div>

      {byteField('fileSize', 'fileSizeUnit', text.t('File size limit'), drafts.fileSizeUnit === 'GB' ? 1 : 100)}
      {byteField('reserve', 'reserveUnit', text.t('Disk reserve'), drafts.reserveUnit === 'GB' ? 1 : 100)}
      <div className={`control-row ${controlsDisabled ? 'is-disabled' : ''}`}>
        <label htmlFor="recording-outputDirectory">{text.t('Output directory')}</label>
        <div className="record-output-control">
          <input
            id="recording-outputDirectory"
            aria-label={text.t('Output directory')}
            title={text.language==='en'?'Relative to the backend recording root':text.hint('Output directory')}
            disabled={controlsDisabled}
            value={drafts.outputDirectory}
            onFocus={() => editing.current.add('outputDirectory')}
            onChange={event => {
              editing.current.add('outputDirectory')
              setDrafts({ outputDirectory: event.target.value })
            }}
            onBlur={() => commitField('outputDirectory')}
            onKeyDown={event => {
              if (event.key === 'Enter') commitField('outputDirectory')
              if (event.key === 'Escape') restoreField('outputDirectory')
            }}
          />
          <button
            aria-label={text.t('Choose output directory')}
            title={text.language==='en'?'Choose a folder below the recording root':text.hint('Choose output directory')}
            disabled={controlsDisabled}
            onMouseDown={event => event.preventDefault()}
            onClick={() => void openDirectoryPicker()}
          >
            …
          </button>
        </div>
      </div>
      {pickerOpen && (
        <div
          className="record-directory-picker"
          role="dialog"
          aria-label={text.t('Choose recording directory')}
        >
          <div className="record-directory-picker__heading">
            <b>{directoryRootName}</b>
            <button aria-label={text.t('Close directory picker')} onClick={() => setPickerOpen(false)}>
              ×
            </button>
          </div>
          <div className="record-directory-list" role="listbox" aria-label={text.t('Recording directories')}>
            {directories.map(directory => (
              <button
                key={directory}
                role="option"
                aria-selected={drafts.outputDirectory === directory}
                disabled={directoryLoading}
                onClick={() => void chooseDirectory(directory)}
              >
                {directory === '.' ? text.t('Default root') : directory}
              </button>
            ))}
            {!directoryLoading && directories.length === 0 && <span>{text.t('No directories found')}</span>}
          </div>
          <div className="record-directory-create">
            <input
              aria-label={text.t('New recording directory')}
              placeholder="field-tests/session-01"
              disabled={directoryLoading}
              value={newDirectory}
              onChange={event => setNewDirectory(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') void createDirectory()
              }}
            />
            <button
              aria-label={text.t('Create recording directory')}
              disabled={directoryLoading}
              onClick={() => void createDirectory()}
            >
              {text.t('Create')}
            </button>
          </div>
          {directoryLoading && <span className="record-save-state">{text.t('Loading directories…')}</span>}
          {directoryError && <div className="record-error" aria-live="polite">{directoryError}</div>}
        </div>
      )}
      {textField('filePrefix', text.t('File prefix'))}

      <div className={`record-disk ${diskNearReserve ? 'is-warning' : ''}`}>
        <span>{text.t('Disk capacity')}</span>
        <b>
          {formatBytes(status?.available_disk_bytes ?? null)} available /{' '}
          {formatBytes(status?.total_disk_bytes ?? null)} total
        </b>
      </div>

      <div className={`record-status is-${state}`} role="status" aria-live="polite">
        <strong>
          <span aria-hidden="true">{state === 'completed' ? '✓' : state === 'failed' ? '⚠' : '●'}</span>{' '}
          {stateLabel(state)}
        </strong>
        {status && state !== 'idle' && (
          <>
            <span>
              {formatElapsed(status.elapsed_s)}
              {targetDuration && Number.isFinite(targetDuration)
                ? ` / ${formatElapsed(targetDuration)}`
                : ''}
            </span>
            <span>
              {formatBytes(status.written_bytes)} · {status.trace_count.toLocaleString()} traces
            </span>
            <span>
              {formatBytes(status.write_rate_bytes_s)}/s · Queue {(queueRatio * 100).toFixed(1)}%
            </span>
            <span>
              Batches {status.batch_count.toLocaleString()} · Gaps {status.gap_count} · Lost{' '}
              {status.lost_trace_count}
            </span>
          </>
        )}
        {reason && <span title={status?.stop_reason ?? undefined}>{reason}</span>}
        {fileName && <span className="record-filename" title={fileName}>{fileName}</span>}
        {status?.last_error && <span className="record-status-error">{status.last_error}</span>}
      </div>

      {warning && status && (
        <div className="record-warning" role="alert">
          {state === 'failed'
            ? status.last_error ?? reason ?? 'Recording failed'
            : `Recorder status: Queue ${(queueRatio * 100).toFixed(0)}%, ${status.rejected_batches} rejected, ${status.gap_count} gaps, ${status.lost_trace_count} lost`}
        </div>
      )}
      {(requestError || pollError) && (
        <div className="record-error" aria-live="polite">
          {requestError ?? pollError}
        </div>
      )}
      {saving && <div className="record-save-state">Saving configuration…</div>}
    </div>
  )
}
