// @vitest-environment jsdom

import { act,cleanup,render } from '@testing-library/react'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { useDeviceStore,useRuntimeStore } from '../stores'
import { SpectrumPanel } from './SpectrumPanel'
import { SpectrogramPanel } from './SpectrogramPanel'

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
})
