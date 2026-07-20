// @vitest-environment jsdom

import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react'
import { afterEach,describe,expect,it,vi } from 'vitest'
import { ResolutionTradeoffControl } from './ResolutionTradeoffControl'
import type { ResolutionTradeoffStepApi } from '../../data/controlApi'
import canonicalSteps from '../../../config/san90-resolution-tradeoff.json'

const steps:ResolutionTradeoffStepApi[]=canonicalSteps
afterEach(cleanup)

describe('ResolutionTradeoffControl',()=>{
  it('renders a capability-driven discrete slider and previews without committing',()=>{
    const commit=vi.fn(async()=>{});render(<ResolutionTradeoffControl steps={steps} actualIndex={2} custom={false} onCommit={commit}/>)
    const slider=screen.getByLabelText('Time/Frequency resolution trade-off') as HTMLInputElement
    expect(slider.min).toBe('0');expect(slider.max).toBe('7');expect(slider.step).toBe('1')
    fireEvent.change(slider,{target:{value:'0'}})
    expect(screen.getByText('EXPECTED')).toBeTruthy();expect(commit).not.toHaveBeenCalled()
  })
  it('commits once on pointer release and supports keyboard commit',async()=>{
    const commit=vi.fn(async()=>{});render(<ResolutionTradeoffControl steps={steps} actualIndex={2} custom={false} onCommit={commit}/>)
    const slider=screen.getByLabelText('Time/Frequency resolution trade-off')
    fireEvent.change(slider,{target:{value:'1'}});fireEvent.pointerUp(slider)
    await waitFor(()=>expect(commit).toHaveBeenCalledWith(1));expect(commit).toHaveBeenCalledTimes(1)
    fireEvent.change(slider,{target:{value:'3'}});fireEvent.keyUp(slider,{key:'ArrowRight'})
    await waitFor(()=>expect(commit).toHaveBeenLastCalledWith(3))
  })
  it('disables transactions and rolls preview back after failure',async()=>{
    const rejected=vi.fn(async()=>{throw new Error('rejected')});const {rerender}=render(<ResolutionTradeoffControl steps={steps} actualIndex={2} custom={false} onCommit={rejected}/>)
    const slider=screen.getByLabelText('Time/Frequency resolution trade-off') as HTMLInputElement
    fireEvent.change(slider,{target:{value:'0'}});fireEvent.pointerUp(slider)
    await waitFor(()=>expect(slider.value).toBe('2'))
    rerender(<ResolutionTradeoffControl steps={steps} actualIndex={2} custom={false} disabled onCommit={rejected}/>)
    expect(slider.disabled).toBe(true)
  })
  it('shows custom state without falsely changing the known actual index',()=>{
    render(<ResolutionTradeoffControl steps={steps} actualIndex={2} custom onCommit={async()=>{}}/>)
    expect(screen.getByText('CUSTOM RBW')).toBeTruthy()
    expect((screen.getByLabelText('Time/Frequency resolution trade-off') as HTMLInputElement).value).toBe('2')
  })
  it('uses measured time and frequency endpoints and fixed display labels',()=>{
    render(<ResolutionTradeoffControl steps={steps} actualIndex={0} custom={false} onCommit={async()=>{}}/>)
    expect(screen.getByText('7.719 MHz')).toBeTruthy();expect(screen.getByText('26')).toBeTruthy();expect(screen.getByText('60 FPS')).toBeTruthy();expect(screen.getByText('480 rows/s')).toBeTruthy()
    cleanup();render(<ResolutionTradeoffControl steps={steps} actualIndex={7} custom={false} onCommit={async()=>{}}/>)
    expect(screen.getByText('60.306 kHz')).toBeTruthy();expect(screen.getByText('3,328')).toBeTruthy();expect(screen.getByText('60 rows/s')).toBeTruthy()
  })
})
