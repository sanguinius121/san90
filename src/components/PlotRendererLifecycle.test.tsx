// @vitest-environment jsdom

import { act,cleanup,fireEvent,render,screen } from '@testing-library/react'
import { afterEach,beforeEach,describe,expect,it,vi } from 'vitest'
import { useDeviceStore,useRuntimeStore,useUiPreferencesStore } from '../stores'
import { UI_LANGUAGE_STORAGE_KEY } from '../data/uiLanguage'
import { SpectrumPanel } from './SpectrumPanel'
import { SpectrumStatusBar } from './SpectrumStatusBar'
import { SpectrogramPanel } from './SpectrogramPanel'
import { AppLayout } from './AppLayout'
import { formatHeaderDateTime } from '../utils/format'

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
  useUiPreferencesStore.setState({language:'en'})
})

afterEach(()=>{
  cleanup()
  vi.unstubAllGlobals()
})

describe('plot renderer lifecycle',()=>{
  it('formats the header clock in the requested Vietnamese date-time form',()=>{
    expect(formatHeaderDateTime(new Date(2026,7,3,20,30,58))).toBe(
      '20:30:58, Ngày 03, Tháng 8, Năm 2026',
    )
  })

  it('persists the ENG/VIỆT language preference without remounting plots',()=>{
    useRuntimeStore.setState({source:'simulator'})
    render(<AppLayout/>)
    const selector=screen.getByLabelText('Ngôn ngữ/Language') as HTMLSelectElement
    expect(Array.from(selector.options).map(option=>option.text)).toEqual(['ENG','VIỆT'])
    expect(selector.value).toBe('en')

    fireEvent.change(selector,{target:{value:'vi'}})
    expect(useUiPreferencesStore.getState().language).toBe('vi')
    expect(localStorage.getItem(UI_LANGUAGE_STORAGE_KEY)).toBe('vi')
    expect(document.documentElement.lang).toBe('vi')
    expect(screen.getByRole('button',{name:'CÀI ĐẶT TẦN SỐ'})).toBeTruthy()
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])
  })

  it('shows the compact PTL-26 Vietnamese product identity without the old subtitle',()=>{
    render(<AppLayout/>)
    expect(screen.getByText('PTL-26')).toBeTruthy()
    expect(screen.getByText('GIÁM SÁT VÔ TUYẾN')).toBeTruthy()
    expect(screen.queryByText('SPECTRUM CONSOLE')).toBeNull()
    expect(screen.queryByText('REAL-TIME RF ANALYSIS')).toBeNull()
  })

  it('shows the localized analyzer-control header without changing its structure',()=>{
    useRuntimeStore.setState({source:'simulator',reconfiguring:false,playbackActive:false})
    render(<AppLayout/>)
    expect(screen.getByText('CÀI ĐẶT THAM SỐ')).toBeTruthy()
    expect(screen.queryByText('ANALYZER CONTROL')).toBeNull()
    expect(screen.queryByText('DEVICE SETTINGS')).toBeNull()
    expect(screen.getByText(/TRỰC TUYẾN/)).toBeTruthy()
    expect(screen.getByRole('button',{name:'Đặt lại bố cục'})).toBeTruthy()
  })

  it('keeps only enlarged Spectrogram FPS and TRACE/ROW metrics',()=>{
    useRuntimeStore.setState({
      source:'san90',connection:'connected',sdkFps:5086,
      tracesPerWaterfallRow:127.5,pointCount:3328,fps:60,waterfallFps:60,
      waterfallBatchFps:60,webglFps:60,spectrogramFps:60,
      replacedSnapshots:1925,droppedFrames:7,
    })
    vi.stubGlobal('fetch',vi.fn(()=>Promise.reject(new Error('offline'))))
    const {container}=render(<AppLayout/>)
    expect(screen.getByText('60 SPECTROGRAM FPS')).toBeTruthy()
    expect(screen.getByText('127.5 TRACE/ROW')).toBeTruthy()
    expect(screen.getByRole('button',{name:'DỪNG'})).toBeTruthy()
    expect(screen.getByRole('button',{name:'KẾT NỐI LẠI'})).toBeTruthy()
    expect(screen.queryByRole('button',{name:'STOP'})).toBeNull()
    expect(screen.queryByRole('button',{name:'RECONNECT'})).toBeNull()
    expect(container.querySelectorAll('.session-primary-metric')).toHaveLength(2)
    expect(screen.queryByText('3328 PTS')).toBeNull()
    expect(screen.queryByText(/ROW\/s/)).toBeNull()
    expect(screen.queryByText(/BATCH\/s/)).toBeNull()
    expect(screen.queryByText(/REPLACED/)).toBeNull()
    expect(screen.queryByText(/INVALID/)).toBeNull()
    expect(screen.queryByText(/SDK FPS/)).toBeNull()
  })

  it('shows the verified center frequency in MHz with exactly two decimals',()=>{
    render(<SpectrogramPanel/>)
    expect(screen.getByText('PHỔ THÁC NƯỚC THỜI GIAN THỰC')).toBeTruthy()
    expect(screen.queryByText('SPECTROGRAM')).toBeNull()
    expect(screen.queryByText('REAL-TIME WATERFALL')).toBeNull()
    expect(screen.getByText('Tần số trung tâm: 2450.00 MHz')).toBeTruthy()

    act(()=>useDeviceStore.setState({centerHz:5.775123e9}))
    expect(screen.getByText('Tần số trung tâm: 5775.12 MHz')).toBeTruthy()
    expect(lifecycle.spectrogramCreated).toHaveBeenCalledTimes(1)
    expect(lifecycle.spectrogramDisposed).not.toHaveBeenCalled()
  })

  it('keeps only the four enlarged spectrum status values',()=>{
    useRuntimeStore.setState({actualRbwHz:60306.09,pointCount:3328,fftSize:4096,fps:60,frequencyBinSpacingHz:30520})
    render(<SpectrumStatusBar/>)
    expect(screen.getByText('CENTER')).toBeTruthy()
    expect(screen.getByText('SPAN')).toBeTruthy()
    expect(screen.getByText('SỐ ĐIỂM FFT')).toBeTruthy()
    expect(screen.getByText('4096')).toBeTruthy()
    expect(screen.getByText('RBW')).toBeTruthy()
    for(const removed of ['START','PTS / FFT','BIN','WINDOW','DETECT','RATE']){
      expect(screen.queryByText(removed)).toBeNull()
    }
  })

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
    expect(screen.getByText('XEM TRƯỚC ẢNH AI')).toBeTruthy()
    expect(screen.queryByText('AI IMAGE PREVIEW')).toBeNull()
    expect(screen.queryByText('LATEST AI INPUT')).toBeNull()
    expect(screen.queryByRole('button',{name:'Frequency'})).toBeNull()
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
    expect([lifecycle.spectrumDisposed.mock.calls.length,lifecycle.spectrogramDisposed.mock.calls.length]).toEqual([0,0])

    fireEvent.click(screen.getByTitle('RF Controls'))
    expect(screen.getByRole('button',{name:'Frequency'})).toBeTruthy()
    expect(screen.queryByText('XEM TRƯỚC ẢNH AI')).toBeNull()
    expect([lifecycle.spectrumCreated.mock.calls.length,lifecycle.spectrogramCreated.mock.calls.length]).toEqual([1,1])
  })
})
