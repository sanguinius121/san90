// @vitest-environment jsdom

import { act,cleanup,fireEvent,render,screen } from '@testing-library/react'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { useDeviceStore,useRuntimeStore } from '../stores'
import { SpectrumPanel } from './SpectrumPanel'
import { SpectrogramPanel } from './SpectrogramPanel'
import { AppLayout } from './AppLayout'

const lifecycle=vi.hoisted(()=>({
  spectrumCreated:vi.fn(),
  spectrumDisposed:vi.fn(),
  spectrogramCreated:vi.fn(),
  spectrogramDisposed:vi.fn(),
}))

vi.mock('../rendering/SpectrumRenderer',async(importOriginal)=>{
  const actual=await importOriginal<typeof import('../rendering/SpectrumRenderer')>()
  return {
    ...actual,
    SpectrumRenderer:class {
      constructor(){lifecycle.spectrumCreated()}
      setFrame(){}
      setPanOffsetPixels(){}
      setPanDimmed(){}
      render(){}
      dispose(){lifecycle.spectrumDisposed()}
    },
  }
})

vi.mock('../rendering/SpectrogramRenderer',async(importOriginal)=>{
  const actual=await importOriginal<typeof import('../rendering/SpectrogramRenderer')>()
  return {
    ...actual,
    SpectrogramRenderer:class {
      textureRowCount=4096
      validRowCount=0
      wrapCount=0
      writeRow=0
      constructor(){lifecycle.spectrogramCreated()}
      addRows(){}
      render(){}
      dispose(){lifecycle.spectrogramDisposed()}
    },
  }
})

class ResizeObserverStub {
  observe(){}
  disconnect(){}
}

beforeEach(()=>{
  vi.stubGlobal('ResizeObserver',ResizeObserverStub)
  vi.stubGlobal('requestAnimationFrame',vi.fn(()=>1))
  vi.stubGlobal('cancelAnimationFrame',vi.fn())
  lifecycle.spectrumCreated.mockClear()
  lifecycle.spectrumDisposed.mockClear()
  lifecycle.spectrogramCreated.mockClear()
  lifecycle.spectrogramDisposed.mockClear()
  useDeviceStore.setState({centerHz:2.45e9,spanHz:101.5625e6})
  useRuntimeStore.setState({configurationGeneration:1,pointCount:3328,ifOverflow:false})
  localStorage.clear()
})

afterEach(()=>{
  cleanup()
  vi.unstubAllGlobals()
})

describe('plot renderer lifecycle',()=>{
  it('keeps both WebGL renderers alive across center, span, and generation updates',()=>{
    const view=render(<><SpectrogramPanel/><SpectrumPanel/></>)
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    act(()=>{
      useDeviceStore.setState({centerHz:5.75e9,spanHz:203.125e6})
      useRuntimeStore.setState({configurationGeneration:2})
    })
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])
    view.unmount()
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([1,1])
  })

  it('lets the live renderer handle a genuine point-count change in place',()=>{
    render(<><SpectrogramPanel/><SpectrumPanel/></>)
    act(()=>useRuntimeStore.setState({pointCount:1664,configurationGeneration:2}))
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])
  })

  it('keeps renderer instances and the five-second window across dock resize',()=>{
    useRuntimeStore.setState({source:'simulator',visibleTimeSpanSeconds:5})
    render(<AppLayout/>)
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    fireEvent.keyDown(screen.getByRole('separator',{name:'Resize right dock'}),{key:'ArrowLeft'})
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])
    expect(useRuntimeStore.getState().visibleTimeSpanSeconds).toBe(5)
  })

  it('switches RF and AI sidebar panels without remounting either renderer',()=>{
    useRuntimeStore.setState({source:'simulator',visibleTimeSpanSeconds:5})
    vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve(new Response(JSON.stringify({
      available:false,
      reason:'waiting',
      sequence:null,
      source:'simulator',
      playback_epoch:null,
      config_id:null,
      configuration_generation:null,
      center_frequency_hz:null,
      frequency_start_hz:null,
      frequency_stop_hz:null,
      width:640,
      height:640,
      created_at_ns:null,
      content_type:'image/png',
    }),{status:200,headers:{'Content-Type':'application/json'}}))))
    render(<AppLayout/>)
    expect(screen.getAllByRole('button',{name:/Frequency|RF Path|Amplitude|Bandwidth|Detection|Record|Playback/}).length).toBeGreaterThan(0)

    fireEvent.click(screen.getByTitle('AI Preview'))
    expect(screen.getByText('AI IMAGE PREVIEW')).toBeTruthy()
    expect(screen.queryByRole('button',{name:'Frequency'})).toBeNull()
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])

    fireEvent.click(screen.getByTitle('RF Controls'))
    expect(screen.getByRole('button',{name:'Frequency'})).toBeTruthy()
    expect(screen.queryByText('AI IMAGE PREVIEW')).toBeNull()
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
  })
})
