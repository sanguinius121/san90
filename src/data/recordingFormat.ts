import type { RecordingStopReason } from '../types/recording'

export type RecordingByteUnit = 'MB' | 'GB'

export const BYTES_PER_RECORDING_UNIT: Readonly<Record<RecordingByteUnit, number>> = {
  MB: 1024 ** 2,
  GB: 1024 ** 3,
}

export const MIN_RECORDING_FILE_BYTES = 16 * 1024

export function bytesToUnit(bytes: number, unit: RecordingByteUnit): number {
  return bytes / BYTES_PER_RECORDING_UNIT[unit]
}

export function unitToBytes(value: number, unit: RecordingByteUnit): number {
  return Math.round(value * BYTES_PER_RECORDING_UNIT[unit])
}

export function cleanNumber(value: number, precision = 3): string {
  if (!Number.isFinite(value)) return '—'
  return String(Number(value.toFixed(precision)))
}

export function formatBytes(bytes: number | null, precision = 1): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return 'Unavailable'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'] as const
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${cleanNumber(value, index === 0 ? 0 : precision)} ${units[index]}`
}

export function formatElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00.0'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  return `${String(minutes).padStart(2, '0')}:${remainder.toFixed(1).padStart(4, '0')}`
}

export function recordingFilename(path: string | null): string | null {
  if (!path) return null
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? null
}

export function validRelativeRecordingDirectory(value: string): boolean {
  if ([...value].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) {
    return false
  }
  if (!value.trim()) return true
  if (value.startsWith('/') || value.startsWith('\\')) return false
  return !value.split(/[\\/]/).some(part => part === '..')
}

export function validRecordingPrefix(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value) && !value.includes('..')
}

export const RECORDING_STOP_REASON_LABELS: Readonly<
  Record<RecordingStopReason, string>
> = {
  user_stop: 'Stopped by user',
  fixed_duration: 'Recording time reached',
  file_size_limit: 'File size limit reached',
  low_disk: 'Low disk space',
  writer_overrun: 'Recorder queue overrun',
  device_disconnect: 'Analyzer disconnected',
  backend_shutdown: 'Backend shutdown',
  writer_error: 'Recording write error',
  start_failure: 'Recording failed to start',
}
