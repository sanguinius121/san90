import { liveFrames } from './liveFrames'
import { analyzerApi, type AnalyzerSettingsApi } from './controlApi'
import { useDeviceStore, useRuntimeStore } from '../stores'

export interface CenterFrequencyLimits {
  minimumHz: number
  maximumHz: number
}

export interface CenterFrequencyCommitResult {
  actualCenterHz: number
  configurationGeneration: number
}

export const DEFAULT_CENTER_FREQUENCY_LIMITS: CenterFrequencyLimits = {
  minimumHz: 1e6,
  maximumHz: 9.5e9,
}

export function applyAnalyzerState(state: AnalyzerSettingsApi) {
  const actual = state.actual
  const previous = useDeviceStore.getState()
  useDeviceStore.setState({
    centerHz: actual.center_frequency_hz,
    spanHz: actual.span_hz,
    referenceDbm: actual.reference_level_dbm,
    attenuationDb: actual.attenuation_db ?? previous.attenuationDb,
    attenuationAutomatic: actual.attenuation_automatic,
    preamplifier: actual.preamplifier ?? previous.preamplifier,
    gainStrategy: actual.gain_strategy ?? previous.gainStrategy,
    amplitudeOffsetDb: actual.amplitude_offset_db ?? previous.amplitudeOffsetDb,
    ifAgc: actual.if_agc_enabled ?? previous.ifAgc,
    ifAgcTargetDbfs: actual.if_agc_target_dbfs ?? previous.ifAgcTargetDbfs,
    ifAgcPeriodS: actual.if_agc_period_s ?? previous.ifAgcPeriodS,
    ifAgcGainDb: actual.if_agc_gain_db === undefined
      ? previous.ifAgcGainDb
      : actual.if_agc_gain_db,
    rbwHz: actual.rbw_hz,
    rbwMode: actual.rbw_mode,
    vbwHz: actual.vbw_hz ?? previous.vbwHz,
    vbwMode: actual.vbw_mode ?? previous.vbwMode,
    resolutionTradeoffIndex:
      actual.resolution_tradeoff_index ?? previous.resolutionTradeoffIndex,
    resolutionTradeoffState:
      actual.resolution_tradeoff_state
      ?? (actual.rbw_mode === 'auto' ? 'auto' : 'custom'),
    window: actual.window ?? previous.window,
    detector: actual.detector ?? previous.detector,
  })
  useRuntimeStore.getState().update({
    configurationGeneration: state.configuration_generation,
    actualSpanHz: actual.span_hz,
    actualRbwHz: actual.rbw_hz,
    pointCount: actual.point_count,
  })
}

export function validateCenterFrequencyHz(
  valueHz: number,
  limits: CenterFrequencyLimits,
) {
  return Number.isFinite(valueHz)
    && valueHz > 0
    && valueHz >= limits.minimumHz
    && valueHz <= limits.maximumHz
}

/**
 * Canonical center-frequency commit used by both the protected numeric input
 * and Spectrum Pan. The simulator branch mirrors one completed configuration
 * transaction by advancing generation once; SAN-90 uses the existing API and
 * verified hardware readback.
 */
export async function commitCenterFrequencyHz(
  valueHz: number,
  limits: CenterFrequencyLimits = DEFAULT_CENTER_FREQUENCY_LIMITS,
): Promise<CenterFrequencyCommitResult | false> {
  const targetHz = Math.round(valueHz)
  const runtime = useRuntimeStore.getState()
  if (!validateCenterFrequencyHz(targetHz, limits)) {
    runtime.update({
      lastError:
        `Center frequency must be between ${limits.minimumHz} Hz and ${limits.maximumHz} Hz`,
    })
    return false
  }
  if (runtime.playbackActive || runtime.source === 'playback') {
    runtime.update({ lastError: 'Center frequency is unavailable during playback' })
    return false
  }
  if (runtime.frequencyScan.running) {
    runtime.update({
      lastError: 'Manual center-frequency changes are disabled while frequency scan is running',
    })
    return false
  }

  runtime.update({ reconfiguring: true, lastError: undefined })
  try {
    if (runtime.source === 'simulator') {
      const latestGeneration = liveFrames.getLatest()?.configurationGeneration ?? 0
      const generation =
        Math.max(runtime.configurationGeneration, latestGeneration) + 1
      useDeviceStore.getState().set('centerHz', targetHz)
      useRuntimeStore.getState().update({ configurationGeneration: generation })
      return {
        actualCenterHz: targetHz,
        configurationGeneration: generation,
      }
    }

    const response = await analyzerApi.put<
      { settings: AnalyzerSettingsApi } | AnalyzerSettingsApi
    >('/api/analyzer/frequency', { center_frequency_hz: targetHz })
    const state = 'settings' in response ? response.settings : response
    applyAnalyzerState(state)
    return {
      actualCenterHz: state.actual.center_frequency_hz,
      configurationGeneration: state.configuration_generation,
    }
  } catch (error) {
    useRuntimeStore.getState().update({
      lastError: error instanceof Error ? error.message : 'Configuration failed',
    })
    if (runtime.source === 'san90') {
      try {
        applyAnalyzerState(await analyzerApi.settings())
      } catch {
        // Preserve the original configuration error and the user's draft.
      }
    }
    return false
  } finally {
    useRuntimeStore.getState().update({ reconfiguring: false })
  }
}
