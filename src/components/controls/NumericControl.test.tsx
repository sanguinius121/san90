// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NumericControl } from './NumericControl'
import { REFERENCE_LEVEL_STEP_DB } from '../ControlSidebar'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('NumericControl', () => {
  it('debounces typed values and commits only once', () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<NumericControl label="Center frequency" value={2.45} unit="GHz" step={0.01} onChange={onChange} />)

    const input = screen.getByLabelText('Center frequency')
    fireEvent.change(input, { target: { value: '2.451' } })
    vi.advanceTimersByTime(300)
    fireEvent.change(input, { target: { value: '2.46' } })
    vi.advanceTimersByTime(599)
    expect(onChange).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(2.46)

    fireEvent.blur(input)
    vi.runAllTimers()
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('commits immediately on Enter and cancels the pending debounce', () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<NumericControl label="Reference level" value={-10} unit="dBm" step={5} onChange={onChange} />)

    const input = screen.getByLabelText('Reference level')
    fireEvent.change(input, { target: { value: '-20' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(-20)

    vi.runAllTimers()
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('accumulates button increments from the displayed draft when hardware keeps the same actual value', () => {
    const onChange = vi.fn()
    render(<NumericControl label="RBW request" value={60.306} unit="kHz" step={10} precision={3} onChange={onChange} />)

    const increase = screen.getByLabelText('Increase RBW request')
    fireEvent.click(increase)
    fireEvent.click(increase)

    expect(onChange).toHaveBeenNthCalledWith(1, 70.306)
    expect(onChange).toHaveBeenNthCalledWith(2, 80.306)
    expect((screen.getByLabelText('RBW request') as HTMLInputElement).value).toBe('80.306')
  })

  it('uses a 10 dB reference-level increment and decrement', () => {
    const onChange = vi.fn()
    render(<NumericControl label="Reference level" value={-20} unit="dBm" step={REFERENCE_LEVEL_STEP_DB} onChange={onChange} />)

    fireEvent.click(screen.getByLabelText('Increase Reference level'))
    fireEvent.click(screen.getByLabelText('Decrease Reference level'))

    expect(onChange).toHaveBeenNthCalledWith(1, -10)
    expect(onChange).toHaveBeenNthCalledWith(2, -20)
  })

  it('does not overwrite a focused center-frequency draft with reported updates', () => {
    const onChange = vi.fn()
    const { rerender } = render(<NumericControl label="Center frequency" value={2.45} unit="GHz" step={0.01} precision={6} verifiedCommit onChange={onChange} />)
    const input = screen.getByLabelText('Center frequency') as HTMLInputElement

    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '2.499' } })
    rerender(<NumericControl label="Center frequency" value={2.46} unit="GHz" step={0.01} precision={6} verifiedCommit onChange={onChange} />)

    expect(input.value).toBe('2.499')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows the verified actual frequency after an explicit commit', async () => {
    const onChange = vi.fn().mockResolvedValue(2.49875)
    render(<NumericControl label="Center frequency" value={2.45} unit="GHz" step={0.01} precision={6} verifiedCommit onChange={onChange} />)
    const input = screen.getByLabelText('Center frequency') as HTMLInputElement

    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '2.499' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(2.499)
    await waitFor(() => expect(input.value).toBe('2.49875'))
  })
})
