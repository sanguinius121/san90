// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FrequencyScanApi, FrequencyScanEntryApi } from '../data/controlApi'
import { useDeviceStore, useRuntimeStore } from '../stores'
import { FrequencyScanControl } from './FrequencyScanControl'

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
      return json(scanStatus(body.entries))
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
  it('starts with the six requested five-second frequencies',async()=>{
    installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await screen.findByLabelText('Scan 6 center frequency')
    expect(Array.from({length:6},(_,index)=>({
      frequency:(screen.getByLabelText(`Scan ${index+1} center frequency`) as HTMLInputElement).value,
      unit:(screen.getByLabelText(`Scan ${index+1} frequency unit`) as HTMLSelectElement).value,
      duration:(screen.getByLabelText(`Scan ${index+1} duration`) as HTMLInputElement).value,
    }))).toEqual([
      {frequency:'400',unit:'MHz',duration:'5'},
      {frequency:'900',unit:'MHz',duration:'5'},
      {frequency:'2.44',unit:'GHz',duration:'5'},
      {frequency:'3.3',unit:'GHz',duration:'5'},
      {frequency:'5',unit:'GHz',duration:'5'},
      {frequency:'5775',unit:'MHz',duration:'5'},
    ])
  })

  it('adds and deletes stable entries without changing unrelated drafts',async()=>{
    installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await screen.findByLabelText('Scan 1 center frequency')
    fireEvent.click(screen.getByText('+ Add frequency'))
    const added=screen.getByLabelText('Scan 7 center frequency') as HTMLInputElement
    fireEvent.change(added,{target:{value:'5.8'}})
    fireEvent.blur(added)
    fireEvent.click(screen.getByLabelText('Delete scan 1'))
    expect(screen.queryByLabelText('Scan 7 center frequency')).toBeNull()
    expect((screen.getByLabelText('Scan 6 center frequency') as HTMLInputElement).value).toBe('5.8')
  })

  it('enables and disables entries and sends only after explicit start',async()=>{
    const {configured}=installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    const enabled=await screen.findByLabelText('Scan 1 enabled') as HTMLInputElement
    expect(enabled.checked).toBe(true)
    fireEvent.click(enabled)
    expect(enabled.checked).toBe(false)
    expect(configured).toHaveLength(0)
    fireEvent.click(screen.getByText('Start scan'))
    await waitFor(()=>expect(configured).toHaveLength(1))
    expect(configured[0]).toHaveLength(6)
    expect(configured[0][0]).toMatchObject({enabled:false,center_frequency_hz:400e6,duration_seconds:5})
    expect(configured[0][1]).toMatchObject({enabled:true,center_frequency_hz:900e6,duration_seconds:5})
  })

  it('switches GHz and MHz without changing canonical Hz or calling the backend',async()=>{
    const {configured}=installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    const frequency=await screen.findByLabelText('Scan 1 center frequency') as HTMLInputElement
    const unit=screen.getByLabelText('Scan 1 frequency unit') as HTMLSelectElement
    expect(Array.from(unit.options,option=>option.value)).toEqual(['GHz','MHz'])
    fireEvent.change(unit,{target:{value:'GHz'}})
    expect(frequency.value).toBe('0.4')
    expect(useDeviceStore.getState().centerHz).toBe(2.45e9)
    expect(configured).toHaveLength(0)
    fireEvent.change(unit,{target:{value:'MHz'}})
    expect(frequency.value).toBe('400')
    expect(useDeviceStore.getState().centerHz).toBe(2.45e9)
  })

  it('rejects invalid frequency and duration before scan start',async()=>{
    const {configured}=installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    const frequency=await screen.findByLabelText('Scan 1 center frequency')
    const duration=screen.getByLabelText('Scan 1 duration')
    fireEvent.change(frequency,{target:{value:'10'}})
    fireEvent.change(duration,{target:{value:'0.1'}})
    fireEvent.click(screen.getByText('Start scan'))
    expect((await screen.findByRole('alert')).textContent).toContain('Enable at least one valid frequency')
    expect(configured).toHaveLength(0)
  })

  it('highlights the backend active entry and displays compact scan status',async()=>{
    const entries=[
      {id:'server-a',enabled:true,center_frequency_hz:2.44e9,duration_seconds:2},
      {id:'server-b',enabled:true,center_frequency_hz:2.46e9,duration_seconds:2},
    ]
    installApi(entries)
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    await waitFor(()=>expect((screen.getByLabelText('Scan 2 center frequency') as HTMLInputElement).value).toBe('2.46'))
    act(()=>useRuntimeStore.setState({frequencyScan:{running:true,state:'dwelling',active_entry_id:'server-b',active_index:2,active_count:2,verified_center_frequency_hz:2.46e9,dwell_duration_seconds:2,remaining_dwell_seconds:1.2,last_error:null}}))
    await waitFor(()=>expect(screen.getByText('Scanning 2/2')).toBeTruthy())
    expect(screen.getByLabelText('Scan 2 center frequency').closest('.frequency-scan-entry')?.classList.contains('is-active')).toBe(true)
    act(()=>useRuntimeStore.setState({reconfiguring:true}))
    expect((screen.getByText('Stop scan') as HTMLButtonElement).disabled).toBe(false)
  })

  it('does not overwrite an entry draft when verified center polling changes',async()=>{
    installApi()
    render(<FrequencyScanControl minimumFrequencyHz={1e6} maximumFrequencyHz={9.5e9}/>)
    const frequency=await screen.findByLabelText('Scan 1 center frequency') as HTMLInputElement
    fireEvent.focus(frequency)
    fireEvent.change(frequency,{target:{value:'2.499'}})
    useDeviceStore.setState({centerHz:5.8e9})
    expect(frequency.value).toBe('2.499')
  })
})
