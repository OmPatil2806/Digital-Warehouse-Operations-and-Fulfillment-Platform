import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SEARCH_DEBOUNCE_MS, SearchInput } from './SearchInput'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

function type(text: string) {
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search' }), { target: { value: text } })
}

describe('SearchInput', () => {
  it('waits until typing pauses, then reports the trimmed text once', () => {
    const onChange = vi.fn()
    render(<SearchInput value="" onChange={onChange} />)

    type('l')
    type('la')
    type('lap ')
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1))
    expect(onChange).not.toHaveBeenCalled()

    act(() => vi.advanceTimersByTime(1))
    expect(onChange).toHaveBeenCalledOnce()
    expect(onChange).toHaveBeenCalledWith('lap')
  })

  it('clear button empties the box immediately', () => {
    const onChange = vi.fn()
    render(<SearchInput value="drill" onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))

    expect(screen.getByRole('searchbox')).toHaveValue('')
    expect(onChange).toHaveBeenCalledWith('')
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS))
    expect(onChange).toHaveBeenCalledOnce() // no late duplicate call
  })

  it('follows changes of value from outside (e.g. browser back)', () => {
    const { rerender } = render(<SearchInput value="first" onChange={vi.fn()} />)

    rerender(<SearchInput value="second" onChange={vi.fn()} />)

    expect(screen.getByRole('searchbox')).toHaveValue('second')
  })

  it('does not call onChange after unmounting', () => {
    const onChange = vi.fn()
    const { unmount } = render(<SearchInput value="" onChange={onChange} />)

    type('abc')
    unmount()
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS))

    expect(onChange).not.toHaveBeenCalled()
  })
})
