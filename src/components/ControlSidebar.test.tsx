// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ControlSidebar } from './ControlSidebar'
import { useDeviceStore, useRuntimeStore } from '../stores'
import type { AnalyzerSettingsApi } from '../data/controlApi'
import canonicalSteps from '../../config/san90-resolution-tradeoff.json'

const capabilities = {
  source: 'san90',
  supported_controls: ['center_frequency_hz', 'reference_level_dbm', 'attenuation_db', 'preamplifier', 'gain_strategy', 'amplitude_offset_db'],
  numeric_ranges: { amplitude_offset_db: { minimum: -100, maximum: 100, step: 1 } },
  center_frequency_min_hz: null,
  center_frequency_max_hz: null,
  center_frequency_step_hz: null,
  reference_level_min_dbm: null,
  reference_level_max_dbm: null,
  supported_attenuation_values_db: null,
  supports_automatic_attenuation: true,
  preamplifier_modes: ['auto', 'off', 'low', 'medium', 'high'],
  gain_strategy_modes: ['low-noise', 'high-linearity'],
  requires_restart_for_frequency: true,
  requires_restart_for_amplitude: true,
  supports_rbw_control: true,
  rbw_control_mode: 'auto-or-manual-numeric',
  supported_rbw_values_hz: [60_306.091, 241_224.365],
  rbw_min_hz: null,
  rbw_max_hz: null,
  rbw_is_discrete: false,
  rbw_is_profile_based: false,
  rbw_changes_point_count: true,
  rbw_changes_span: false,
  rbw_requires_restart: true,
  window_modes: ['flat-top', 'blackman-nuttall', 'low-sidelobe', 'rectangular', 'kaiser'],
  detector_modes: ['sample', 'positive-peak', 'average', 'negative-peak', 'rms', 'auto-peak'],
  window_requires_restart: true,
  detector_requires_restart: true,
}

const tradeoffSteps=canonicalSteps

const tradeoffCapabilities={...capabilities,
  supported_controls:[...capabilities.supported_controls,'rbw_hz','rbw_mode','resolution_tradeoff_index'],
  supports_resolution_tradeoff:true,resolution_tradeoff_steps:tradeoffSteps,
  resolution_tradeoff_min_index:0,resolution_tradeoff_max_index:7,
  resolution_tradeoff_direction:{left:'time',right:'frequency'},
  default_resolution_tradeoff_index:5,supports_auto_rbw:true,
}

function settings(center = 2.45e9, generation = 1): AnalyzerSettingsApi {
  return {
    requested: { center_frequency_hz: center, reference_level_dbm: 0, attenuation_db: null, preamplifier: 'off', gain_strategy: 'low-noise', rbw_hz: null, rbw_mode: 'auto', window: null, detector: null, amplitude_offset_db: 0 },
    actual: {
      center_frequency_hz: center,
      start_frequency_hz: center - 50_781_250,
      stop_frequency_hz: center + 50_781_250,
      span_hz: 101_562_500,
      reference_level_dbm: 0,
      attenuation_db: 0,
      attenuation_automatic: true,
      preamplifier: 'off',
      gain_strategy: 'low-noise',
      rbw_hz: 60_306.091,
      rbw_mode: 'auto',
      window: 'blackman-nuttall',
      detector: 'positive-peak',
      fft_size: 4096,
      scale_to_dbm: 0.5,
      offset_to_dbm: -113,
      point_count: 3328,
      resolution_tradeoff_index: null,
      resolution_tradeoff_state: 'auto',
      resolution_tradeoff_step_id:null,
      frequency_bin_spacing_hz:30_517.578125,
      amplitude_offset_db: 0,
    },
    configuration_generation: generation,
  }
}

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

beforeEach(() => {
  useRuntimeStore.setState({ source: 'san90', reconfiguring: false, lastError: undefined, configurationGeneration: 0 })
  useDeviceStore.setState({ centerHz: 2.45e9, stepHz: 10e6 })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('ControlSidebar hardware controls', () => {
  it('preserves an amplitude-offset draft during polling and commits one verified value', async () => {
    let current = settings()
    const offsetRequests: number[] = []
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/analyzer/capabilities')) return json(capabilities)
      if (url.endsWith('/api/analyzer/settings')) return json(current)
      if (url.endsWith('/api/analyzer/amplitude/offset') && init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as {amplitude_offset_db:number}
        offsetRequests.push(request.amplitude_offset_db)
        current = structuredClone(current)
        current.requested.amplitude_offset_db = request.amplitude_offset_db
        current.actual.amplitude_offset_db = request.amplitude_offset_db
        return json(current)
      }
      return json({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    useRuntimeStore.setState({ ifOverflow: true })
    render(<ControlSidebar />)

    const offset = await screen.findByLabelText('Amplitude offset') as HTMLInputElement
    await waitFor(() => expect(offset.disabled).toBe(false))
    fireEvent.focus(offset)
    fireEvent.change(offset, { target: { value: '10' } })

    // A low-rate status poll may update the active store value, but not the draft.
    useDeviceStore.setState({ amplitudeOffsetDb: -4 })
    expect(offset.value).toBe('10')
    expect(offsetRequests).toHaveLength(0)

    fireEvent.keyDown(offset, { key: 'Enter' })
    await waitFor(() => expect(offsetRequests).toEqual([10]))
    await waitFor(() => expect(offset.value).toBe('10'))
    expect(useDeviceStore.getState().referenceDbm).toBe(0)
    expect(useDeviceStore.getState().attenuationDb).toBe(0)
    expect(useRuntimeStore.getState().ifOverflow).toBe(true)
  })

  it('keeps automatic attenuation read-only and preserves a manual draft until verified readback', async () => {
    let current = settings()
    current.actual.attenuation_db = 3
    current.actual.attenuation_automatic = true
    current.actual.preamplifier = 'auto'
    const attenuationRequests: Array<{mode:string;attenuation_db?:number}> = []
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/analyzer/capabilities')) return json(capabilities)
      if (url.endsWith('/api/analyzer/settings')) return json(current)
      if (url.endsWith('/api/analyzer/amplitude/attenuation') && init?.method === 'PUT') {
        const request = JSON.parse(String(init.body)) as {mode:string;attenuation_db?:number}
        attenuationRequests.push(request)
        current = structuredClone(current)
        if (request.mode === 'manual') {
          current.requested.attenuation_db = request.attenuation_db ?? null
          current.actual.attenuation_automatic = false
          current.actual.attenuation_db = Math.max(3, Math.floor((request.attenuation_db ?? 3) / 3) * 3)
          current.actual.preamplifier = 'off'
        }
        current.configuration_generation++
        return json(current)
      }
      return json({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ControlSidebar />)

    const attenuation = await screen.findByLabelText('Attenuation') as HTMLInputElement
    const mode = await screen.findByLabelText('Attenuation mode') as HTMLSelectElement
    await waitFor(() => expect(attenuation.value).toBe('3'))
    expect(mode.value).toBe('auto')
    expect(attenuation.disabled).toBe(true)

    fireEvent.change(mode, { target: { value: 'manual' } })
    await waitFor(() => expect(attenuation.disabled).toBe(false))
    expect(useDeviceStore.getState().preamplifier).toBe('off')

    fireEvent.click(screen.getByLabelText('Increase Attenuation'))
    await waitFor(() => expect(attenuation.value).toBe('6'))
    expect(attenuationRequests.at(-1)).toEqual({ mode: 'manual', attenuation_db: 6 })

    fireEvent.focus(attenuation)
    fireEvent.change(attenuation, { target: { value: '10' } })
    useDeviceStore.setState({ attenuationDb: 3 })
    expect(attenuation.value).toBe('10')
    expect(attenuationRequests).toHaveLength(2)

    fireEvent.keyDown(attenuation, { key: 'Enter' })
    await waitFor(() => expect(attenuation.value).toBe('9'))
    expect(attenuationRequests.at(-1)).toEqual({ mode: 'manual', attenuation_db: 10 })
  })

  it('shows the actual accepted value and exposes a control error without retaining a false value', async () => {
    let current = settings()
    let failNext = false
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/analyzer/capabilities')) return json(capabilities)
      if (url.endsWith('/api/analyzer/settings')) return json(current)
      if (url.endsWith('/api/analyzer/frequency') && init?.method === 'PUT') {
        if (failNext) return json({ error: { code: 'SDK_CONFIGURATION_FAILED', message: 'Device rejected frequency' } }, 422)
        current = settings(2.459e9, 2)
        return json({ settings: current })
      }
      return json({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ControlSidebar />)

    const center = await screen.findByLabelText('Center frequency') as HTMLInputElement
    await waitFor(() => expect(center.value).toBe('2.45'))

    fireEvent.click(screen.getByLabelText('Increase Center frequency'))
    await waitFor(() => expect(center.value).toBe('2.459'))
    expect(useDeviceStore.getState().centerHz).toBe(2.459e9)
    expect(useRuntimeStore.getState().configurationGeneration).toBe(2)

    failNext = true
    fireEvent.click(screen.getByLabelText('Increase Center frequency'))
    expect((await screen.findByRole('alert')).textContent).toContain('Device rejected frequency')
    await waitFor(() => expect(center.value).toBe('2.469'))
    expect(useDeviceStore.getState().centerHz).toBe(2.459e9)
  })

  it('applies a full coerced RBW response atomically, including point count, window, and detector', async () => {
    let current = settings()
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/api/analyzer/capabilities')) return json(capabilities)
      if (url.endsWith('/api/analyzer/settings')) return json(current)
      if (url.endsWith('/api/analyzer/bandwidth/rbw') && init?.method === 'PUT') {
        current = settings(2.45e9, 3)
        current.requested.rbw_mode = 'manual'
        current.requested.rbw_hz = 300_000
        current.actual.rbw_mode = 'manual'
        current.actual.rbw_hz = 241_224.365
        current.actual.point_count = 832
        current.actual.fft_size = 1024
        current.actual.window = 'rectangular'
        current.actual.detector = 'average'
        return json(current)
      }
      return json({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ControlSidebar />)

    const rbwMode = await screen.findByLabelText('RBW mode')
    await waitFor(() => expect((rbwMode as HTMLSelectElement).disabled).toBe(false))
    fireEvent.change(rbwMode, { target: { value: 'manual' } })

    await waitFor(() => expect(useRuntimeStore.getState().configurationGeneration).toBe(3))
    expect(useRuntimeStore.getState().pointCount).toBe(832)
    expect(useDeviceStore.getState().rbwHz).toBe(241_224.365)
    expect(useDeviceStore.getState().window).toBe('rectangular')
    expect(useDeviceStore.getState().detector).toBe('average')
  })

  it('keeps Auto separate and snaps the manual slider to hardware readback',async()=>{
    let current=settings()
    const fetchMock=vi.fn((input:string|URL|Request,init?:RequestInit)=>{
      const url=String(input)
      if(url.endsWith('/api/analyzer/capabilities'))return json(tradeoffCapabilities)
      if(url.endsWith('/api/analyzer/settings'))return json(current)
      if(url.endsWith('/api/analyzer/resolution-tradeoff')&&init?.method==='PUT'){
        current=settings(2.45e9,2);current.requested.rbw_mode='manual';current.requested.rbw_hz=300_000
        current.actual.rbw_mode='manual';current.actual.rbw_hz=120_612.183;current.actual.point_count=1664
        current.actual.fft_size=2048;current.actual.resolution_tradeoff_index=6;current.actual.resolution_tradeoff_state='matched';current.actual.resolution_tradeoff_step_id='time-6'
        return json({actual_index:6,spectrum_publish_fps:60,webgl_target_fps:60,waterfall_rows_per_second:120,waterfall_rows_per_batch:2,visible_rows:600,settings:current})
      }
      if(url.endsWith('/api/analyzer/bandwidth/rbw')&&init?.method==='PUT'){
        current=settings(2.45e9,3);return json(current)
      }
      return json({},404)
    })
    vi.stubGlobal('fetch',fetchMock);render(<ControlSidebar/>)
    const rbwMode=await screen.findByLabelText('RBW mode')
    await waitFor(()=>expect((rbwMode as HTMLSelectElement).value).toBe('auto'))
    expect(screen.queryByLabelText('Time/Frequency resolution trade-off')).toBeNull()
    fireEvent.change(rbwMode,{target:{value:'manual'}})
    const slider=await screen.findByLabelText('Time/Frequency resolution trade-off') as HTMLInputElement
    await waitFor(()=>expect(slider.value).toBe('7'))
    expect(fetchMock.mock.calls.filter(([url])=>String(url).endsWith('/api/analyzer/resolution-tradeoff'))).toHaveLength(0)
    fireEvent.change(slider,{target:{value:'6'}});fireEvent.pointerUp(slider)
    await waitFor(()=>expect(slider.value).toBe('6'))
    expect(fetchMock.mock.calls.filter(([url])=>String(url).endsWith('/api/analyzer/resolution-tradeoff'))).toHaveLength(1)
    fireEvent.change(rbwMode,{target:{value:'auto'}})
    await waitFor(()=>expect(screen.queryByLabelText('Time/Frequency resolution trade-off')).toBeNull())
  })
})
