// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToolRail } from './ToolRail'
import { useDisplayStore, useRuntimeStore } from '../stores'

afterEach(cleanup)
beforeEach(()=>{
  useDisplayStore.setState({activeTool:'marker',panPhase:'off'})
  useRuntimeStore.setState({source:'simulator',connection:'mock',reconfiguring:false,playbackActive:false,frequencyScan:{...useRuntimeStore.getState().frequencyScan,running:false,state:'idle'}})
})

describe('ToolRail', () => {
  it('shows RF and AI sidebar navigation before the supported analysis tools', () => {
    render(<ToolRail />)

    const buttons = screen.getAllByRole('button')
    expect(buttons.map(button => button.getAttribute('title'))).toEqual([
      'RF Controls',
      'AI Preview',
      'Peak Search',
      'Marker',
      'Pan Off',
    ])
    expect(screen.queryByTitle('Graph')).toBeNull()
    expect(screen.queryByTitle('Trace')).toBeNull()
    expect(screen.queryByTitle('Zoom')).toBeNull()
  })

  it('selects the requested sidebar panel without changing analysis tools', () => {
    const onPanelChange = vi.fn()
    const view = render(<ToolRail panel="rf" onPanelChange={onPanelChange} />)
    expect(screen.getByTitle('RF Controls').getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByTitle('AI Preview'))
    expect(onPanelChange).toHaveBeenCalledWith('ai-preview')

    view.rerender(<ToolRail panel="ai-preview" onPanelChange={onPanelChange} />)
    expect(screen.getByTitle('AI Preview').getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByTitle('RF Controls').getAttribute('aria-pressed')).toBe('false')
  })

  it('uses compact Pan badges that cannot widen the fixed navigation rail',()=>{
    render(<ToolRail/>)
    const pan=screen.getByRole('button',{name:'Pan Off'})
    fireEvent.click(pan)
    expect(screen.getByText('ON')).toBeTruthy()
    act(()=>useDisplayStore.setState({panPhase:'dragging'}))
    expect(screen.getByText('DRAG')).toBeTruthy()
    expect(screen.queryByText('DRAGGING')).toBeNull()
    expect(pan.getAttribute('data-pan-state')).toBe('dragging')
  })
})
