// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FrequencyScanApi, FrequencyScanEntryApi } from '../data/controlApi'
import { useDeviceStore, useRuntimeStore } from '../stores'
import { FrequencyScanControl } from './FrequencyScanControl'

function apiEntry(
  id:string,
  center_frequency_hz:number,
  overrides:Partial<FrequencyScanEntryApi>={},
):FrequencyScanEntryApi {
  return {
    id,
    enabled:true,
    center_frequency_hz,
    duration_ms:5000,
    step_hz:10e6,
    display_unit:'MHz',
    step_unit:'MHz',
    ...overrides,
  }
}

function json(body:unknown,status=200) {
  return Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}))
}

function scanStatus(entries:FrequencyScanEntryApi[]=[],overrides:Partial<FrequencyScanApi>={}):FrequencyScanApi {
  return {
    entries,
    running:false,
    state:'idle',
    active_entry_id:null,
    active_index:null,
    active_count:entries.filter(entry=>entry.enabled).length,
    verified_center_frequency_hz:null,
    dwell_duration_seconds:null,
    remaining_dwell_seconds:null,
    last_error:null,
    configuration_save_error:null,
    configuration_load_warning:null,
    ...overrides,
  }
}

function installApi(initialEntries:FrequencyScanEntryApi[]=[]){
  const configured:FrequencyScanEntryApi[][]=[]
  const fetchMock=vi.fn((input:string|URL|Request,init?:RequestInit)=>{
    const url=String(input)
    if(url.endsWith('/api/analyzer/frequency-scan/status'))return json(scanStatus(initialEntries))
    if(url.endsWith('/api/analyzer/frequency-scan/config')&&init?.method==='PUT'){
      const body=JSON.parse(String(init.body)) as {entries:FrequencyScanEntryApi[]}
      configured.push(body.entries)
      const runtime=useRuntimeStore.getState().frequencyScan
      return json(scanStatus(body.entries,{
        running:runtime.running,
        state:runtime.state,
        active_entry_id:runtime.active_entry_id,
        active_index:runtime.active_index,
        active_count:runtime.active_count,
        verified_center_frequency_hz:runtime.verified_center_frequency_hz,
        dwell_duration_seconds:runtime.dwell_duration_seconds,
        remaining_dwell_seconds:runtime.remaining_dwell_seconds,
        last_error:runtime.last_error,
      }))
    }
    if(url.endsWith('/api/analyzer/frequency-scan/start')&&init?.method==='POST'){
      const entries=configured.at(-1)??initialEntries
      return json(scanStatus(entries,{running:true,state:'tuning',active_entry_id:entries.find(entry=>entry.enabled)?.id??null,active_index:1}))
    }
    if(url.endsWith('/api/analyzer/frequency-scan/stop')&&init?.method==='POST')return json(scanStatus(configured.at(-1)??initialEntries))
    return json({},404)
  })
  vi.stubGlobal('fetch',fetchMock)
  return {configured,fetchMock}
}

beforeEach(()=>{
  useDeviceStore.setState({centerHz:2.45e9})
  useRuntimeStore.setState({
    reconfiguring:false,
    frequencyScan:{running:false,state:'idle',active_entry_id:null,active_index:null,active_count:0,verified_center_frequency_hz:null,dwell_duration_seconds:null,remaining_dwell_seconds:null,last_error:null},
  })
})

afterEach(()=>{
  cleanup()
  vi.restoreAllMocks()
})

describe('FrequencyScanControl',()=>{
  it('renders the six defaults in compact three-row entries with independent 10 MHz steps',async()=>{
    installApi([
      apiEntry('scan-entry-1',400e6),
      apiEntry('scan-entry-2',900e6),
      apiEntry('scan-entry-3',2.44e9,{display_unit:'GHz'}),
      apiEntry('scan-entry-4',3.3e9,{display_unit:'GHz'}),
      apiEntry('scan-entry-5',5e9,{display_unit:'GHz'}),
      apiEntry('scan-entry-6',5.775e9),
    ])
    const {container}=render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await screen.findByLabelText('Scan 6 center frequency')
    expect(container.querySelectorAll('.frequency-scan-entry')).toHaveLength(6)
    expect(container.querySelectorAll('.frequency-scan-entry__heading')).toHaveLength(6)
    expect(container.querySelectorAll('.frequency-scan-entry__frequency-row')).toHaveLength(6)
    expect(container.querySelectorAll('.frequency-scan-entry__detail-row')).toHaveLength(6)
    expect((screen.getByLabelText('Scan 6 center frequency') as HTMLInputElement).value).toBe('5775')
    expect((screen.getByLabelText('Scan 6 frequency unit') as HTMLSelectElement).value).toBe('MHz')
    expect((screen.getByLabelText('Scan 1 step') as HTMLInputElement).value).toBe('10')
    expect((screen.getByLabelText('Scan 1 duration') as HTMLInputElement).value).toBe('5')
  })

  it('increments and decrements by each entry own canonical step',async()=>{
    const {configured}=installApi([
      apiEntry('a',2450e6,{step_hz:10e6}),
      apiEntry('b',2450e6,{step_hz:25e6}),
    ])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 2 step') as HTMLInputElement).value).toBe('25'))
    fireEvent.click(screen.getByLabelText('Increase scan 1 frequency'))
    await waitFor(()=>expect(configured.at(-1)?.[0].center_frequency_hz).toBe(2460e6))
    expect(configured.at(-1)?.[1].center_frequency_hz).toBe(2450e6)
    fireEvent.click(screen.getByLabelText('Decrease scan 2 frequency'))
    await waitFor(()=>expect(configured.at(-1)?.[1].center_frequency_hz).toBe(2425e6))
    expect(configured.at(-1)?.[0].step_hz).toBe(10e6)
    expect(configured.at(-1)?.[1].step_hz).toBe(25e6)
  })

  it('preserves canonical center Hz when switching MHz and GHz and saves the preference',async()=>{
    const {configured}=installApi([apiEntry('a',2450e6)])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement).value).toBe('2450'))
    fireEvent.change(screen.getByLabelText('Scan 1 frequency unit'),{target:{value:'GHz'}})
    expect((screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement).value).toBe('2.45')
    await waitFor(()=>expect(configured.at(-1)?.[0]).toMatchObject({center_frequency_hz:2450e6,display_unit:'GHz'}))
  })

  it('preserves canonical step Hz when switching MHz and GHz and saves the preference',async()=>{
    const {configured}=installApi([apiEntry('a',2450e6,{step_hz:10e6})])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement).value).toBe('2450'))
    fireEvent.change(screen.getByLabelText('Scan 1 step unit'),{target:{value:'GHz'}})
    expect((screen.getByLabelText('Scan 1 step') as HTMLInputElement).value).toBe('0.01')
    await waitFor(()=>expect(configured.at(-1)?.[0]).toMatchObject({step_hz:10e6,step_unit:'GHz'}))
  })

  it('rejects empty, zero, negative, and non-finite step drafts',async()=>{
    const {configured}=installApi([apiEntry('a',2450e6)])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement).value).toBe('2450'))
    for(const value of ['', '0', '-1', 'NaN', 'Infinity']){
      const step=screen.getByLabelText('Scan 1 step')
      fireEvent.change(step,{target:{value}})
      fireEvent.blur(step)
      expect((await screen.findByRole('alert')).textContent).toContain('outside the supported range')
    }
    expect(configured).toHaveLength(0)
  })

  it('disables step buttons that would leave the analyzer frequency range',async()=>{
    installApi([
      apiEntry('low',10e6,{step_hz:10e6}),
      apiEntry('high',90e6,{step_hz:20e6}),
    ])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={100e6}/>)
    await screen.findByLabelText('Scan 2 center frequency')
    expect((screen.getByLabelText('Decrease scan 1 frequency') as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByLabelText('Increase scan 2 frequency') as HTMLButtonElement).disabled).toBe(true)
  })

  it('does not let a delayed status response overwrite center or step drafts',async()=>{
    let resolveStatus:(response:Response)=>void=()=>{}
    const statusPromise=new Promise<Response>(resolve=>{resolveStatus=resolve})
    vi.stubGlobal('fetch',vi.fn(()=>statusPromise))
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    const frequency=screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement
    const step=screen.getByLabelText('Scan 1 step') as HTMLInputElement
    fireEvent.change(frequency,{target:{value:'499'}})
    fireEvent.change(step,{target:{value:'7'}})
    resolveStatus(new Response(JSON.stringify(scanStatus([apiEntry('server',2.45e9,{step_hz:25e6})])),{status:200,headers:{'Content-Type':'application/json'}}))
    await act(async()=>{await Promise.resolve()})
    expect(frequency.value).toBe('499')
    expect(step.value).toBe('7')
  })

  it('restores backend order, enabled state, units, duration, and steps on page load',async()=>{
    installApi([
      apiEntry('saved-b',3.3e9,{enabled:false,duration_ms:1500,step_hz:0.025e9,display_unit:'GHz',step_unit:'GHz'}),
      apiEntry('saved-a',900e6,{duration_ms:2500,step_hz:5e6}),
    ])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 1 center frequency') as HTMLInputElement).value).toBe('3.3'))
    expect((screen.getByLabelText('Scan 1 enabled') as HTMLInputElement).checked).toBe(false)
    expect((screen.getByLabelText('Scan 1 frequency unit') as HTMLSelectElement).value).toBe('GHz')
    expect((screen.getByLabelText('Scan 1 step') as HTMLInputElement).value).toBe('0.025')
    expect((screen.getByLabelText('Scan 1 duration') as HTMLInputElement).value).toBe('1.5')
    expect((screen.getByLabelText('Scan 2 center frequency') as HTMLInputElement).value).toBe('900')
  })

  it('persists enable, delete, add, and duration changes on commit',async()=>{
    const {configured}=installApi([apiEntry('a',2.45e9),apiEntry('b',2.5e9)])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await screen.findByLabelText('Scan 2 center frequency')
    fireEvent.click(screen.getByLabelText('Scan 1 enabled'))
    await waitFor(()=>expect(configured.at(-1)?.[0].enabled).toBe(false))
    fireEvent.change(screen.getByLabelText('Scan 2 duration'),{target:{value:'2'}})
    fireEvent.blur(screen.getByLabelText('Scan 2 duration'))
    await waitFor(()=>expect(configured.at(-1)?.[1].duration_ms).toBe(2000))
    fireEvent.click(screen.getByLabelText('Delete scan 1'))
    await waitFor(()=>expect(configured.at(-1)?.map(entry=>entry.id)).toEqual(['b']))
    fireEvent.click(screen.getByText('+ Add frequency'))
    await waitFor(()=>expect(configured.at(-1)).toHaveLength(2))
  })

  it('allows future-entry edits while scanning without stopping the current dwell',async()=>{
    const {configured}=installApi([apiEntry('a',2.45e9),apiEntry('b',2.5e9)])
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await screen.findByLabelText('Scan 2 center frequency')
    act(()=>useRuntimeStore.setState({frequencyScan:{running:true,state:'dwelling',active_entry_id:'a',active_index:1,active_count:2,verified_center_frequency_hz:2.45e9,dwell_duration_seconds:5,remaining_dwell_seconds:4,last_error:null}}))
    const future=screen.getByLabelText('Scan 2 center frequency') as HTMLInputElement
    expect(future.disabled).toBe(false)
    fireEvent.change(future,{target:{value:'2550'}})
    fireEvent.blur(future)
    await waitFor(()=>expect(configured.at(-1)?.[1].center_frequency_hz).toBe(2550e6))
    expect(useRuntimeStore.getState().frequencyScan.running).toBe(true)
  })
})
