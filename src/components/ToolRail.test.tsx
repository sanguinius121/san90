// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToolRail } from './ToolRail'

afterEach(cleanup)

describe('ToolRail', () => {
  it('shows RF and AI sidebar navigation before the supported analysis tools', () => {
    render(<ToolRail />)

    const buttons = screen.getAllByRole('button')
    expect(buttons.map(button => button.getAttribute('title'))).toEqual([
      'RF Controls',
      'AI Preview',
      'Peak Search',
      'Marker',
      'Pan',
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
})
