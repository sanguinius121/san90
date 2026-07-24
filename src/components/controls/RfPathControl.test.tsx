// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRfSwitchStore } from '../../stores'
import { RfPathControl } from './RfPathControl'
import type { RfPathId, RfSwitchStatusApi } from '../../data/controlApi'

const paths=Array.from({length:8},(_,index)=>({id:`rf${index+1}`,rf_channel:`RF${index+1}`,address:index,label:`RF${index+1} — ${index===0?'2.4/5.8 GHz LNA':index===7?'Wideband antenna':'Auxiliary'}`,external_lna:index===0}))
const status=(path:RfPathId='rf8',matches=true):RfSwitchStatusApi=>({connection_state:matches?'available':'error',hardware_present:true,available:matches,connected:matches,backend:'simulator',simulated:true,requested_path:path,requested_port:path,reported_path:matches?path:'rf8',reported_port:matches?path:'rf8',expected_fail_safe_path:null,raw_address:matches?Number(path.slice(2))-1:7,raw_gpio_value:matches?(Number(path.slice(2))-1)<<4:112,gpio_value:matches?(Number(path.slice(2))-1)<<4:112,readback_matches_request:matches,verification:matches?'verified':'mismatch',last_error:matches?null:'mismatch',reconnect_attempts:0,last_connected_at:1,last_disconnected_at:null,updated_at_monotonic:1})
const json=(body:unknown,statusCode=200)=>Promise.resolve(new Response(JSON.stringify(body),{status:statusCode,headers:{'Content-Type':'application/json'}}))

beforeEach(()=>{
  useRfSwitchStore.setState({...status(),loading:true,applying:false})
})
afterEach(()=>{cleanup();vi.restoreAllMocks()})

describe('RfPathControl',()=>{
  it('renders all eight capability-driven ports and applies one manual selection',async()=>{
    const fetchMock=vi.fn((input:string|URL|Request,init?:RequestInit)=>{
      const url=String(input)
      if(url.endsWith('/capabilities'))return json({enabled:true,default_path:'rf8',selection_policy:'session-only-manual',paths})
      if(url.endsWith('/status'))return json(status())
      if(url.endsWith('/path')&&init?.method==='PUT')return json(status('rf1'))
      return json({},404)
    })
    vi.stubGlobal('fetch',fetchMock)
    render(<RfPathControl/>)
    const select=await screen.findByLabelText('RF input path') as HTMLSelectElement
    await waitFor(()=>expect(select.disabled).toBe(false))
    expect(select.options).toHaveLength(8)
    fireEvent.change(select,{target:{value:'rf1'}})
    await screen.findByText('EXTERNAL LNA ACTIVE')
    expect(useRfSwitchStore.getState().reported_path).toBe('rf1')
    const request=fetchMock.mock.calls.find(([url,init])=>String(url).endsWith('/path')&&(init as RequestInit)?.method==='PUT')
    expect(request?.[1]?.body).toBe(JSON.stringify({path:'rf1'}))
  })

  it('does not claim the LNA is active on readback mismatch',async()=>{
    vi.stubGlobal('fetch',vi.fn((input:string|URL|Request)=>String(input).endsWith('/capabilities')?json({enabled:true,default_path:'rf8',selection_policy:'session-only-manual',paths}):json(status('rf1',false))))
    render(<RfPathControl/>)
    await screen.findByText('Requested path is not verified by GPIO readback.')
    expect(screen.queryByText('EXTERNAL LNA ACTIVE')).toBeNull()
    expect(screen.getByText('RF8')).toBeTruthy()
  })

  it('keeps selection unavailable when support is disabled',async()=>{
    vi.stubGlobal('fetch',vi.fn((input:string|URL|Request)=>String(input).endsWith('/capabilities')?json({enabled:false,default_path:'rf8',selection_policy:'session-only-manual',paths}):json({...status(),connection_state:'disabled',hardware_present:false,available:false,connected:false,requested_path:null,reported_path:null,raw_address:null,raw_gpio_value:null,verification:'unavailable',readback_matches_request:false})))
    render(<RfPathControl/>)
    const select=await screen.findByLabelText('RF input path') as HTMLSelectElement
    await waitFor(()=>expect(select.disabled).toBe(true))
    expect(screen.getByText('DISABLED')).toBeTruthy()
  })

  it('shows an unpowered disconnect and disables selection while reconnecting',async()=>{
    const disconnected={...status(),connection_state:'reconnecting',hardware_present:false,available:false,connected:false,requested_path:null,requested_port:null,reported_path:null,reported_port:null,expected_fail_safe_path:null,raw_address:null,raw_gpio_value:null,gpio_value:null,verification:'unavailable',readback_matches_request:false,reconnect_attempts:3,last_error:'FT232H is not connected'}
    vi.stubGlobal('fetch',vi.fn((input:string|URL|Request)=>String(input).endsWith('/capabilities')?json({enabled:true,default_path:'rf8',selection_policy:'session-only-manual',paths}):json(disconnected)))
    render(<RfPathControl/>)
    const select=await screen.findByLabelText('RF input path') as HTMLSelectElement
    await waitFor(()=>expect(select.disabled).toBe(true))
    expect(screen.getByText('RECONNECTING · 3')).toBeTruthy()
    expect(screen.getByText(/externally powered RF switch are disconnected/)).toBeTruthy()
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
  })

  it('labels powered RF8 fail-safe as expected but unverified',async()=>{
    const unverified={...status(),connection_state:'reconnecting',available:false,connected:false,requested_path:null,requested_port:null,reported_path:null,reported_port:null,expected_fail_safe_path:'rf8',raw_address:null,raw_gpio_value:null,gpio_value:null,verification:'unverified',readback_matches_request:false,reconnect_attempts:1,last_error:'transport stopped'}
    vi.stubGlobal('fetch',vi.fn((input:string|URL|Request)=>String(input).endsWith('/capabilities')?json({enabled:true,default_path:'rf8',selection_policy:'session-only-manual',paths}):json(unverified)))
    render(<RfPathControl/>)
    await screen.findByText(/expected pull-up fail-safe path, but it is not verified/)
    expect((screen.getByLabelText('RF input path') as HTMLSelectElement).disabled).toBe(true)
  })
})
