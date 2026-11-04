import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useToast } from '../hooks/useToast'
import { TOAST_DURATION_MS } from './toastContext'
import { ToastProvider } from './ToastProvider'

function Buttons() {
  const toast = useToast()
  return (
    <>
      <button onClick={() => toast.success('Product created')}>ok</button>
      <button onClick={() => toast.error('Could not save')}>fail</button>
      <button onClick={() => toast.info('Heads up')}>info</button>
    </>
  )
}

function renderToasts() {
  render(
    <ToastProvider>
      <Buttons />
    </ToastProvider>,
  )
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ToastProvider', () => {
  it('shows success as a status and errors as an alert', () => {
    renderToasts()

    fireEvent.click(screen.getByText('ok'))
    fireEvent.click(screen.getByText('fail'))

    expect(screen.getByRole('status')).toHaveTextContent('Product created')
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save')
  })

  it('hides toasts automatically, errors later than success', () => {
    renderToasts()
    fireEvent.click(screen.getByText('ok'))
    fireEvent.click(screen.getByText('fail'))

    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS.success))
    expect(screen.queryByText('Product created')).not.toBeInTheDocument()
    expect(screen.getByText('Could not save')).toBeInTheDocument()

    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS.error - TOAST_DURATION_MS.success))
    expect(screen.queryByText('Could not save')).not.toBeInTheDocument()
  })

  it('can be dismissed by hand', () => {
    renderToasts()
    fireEvent.click(screen.getByText('info'))

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))

    expect(screen.queryByText('Heads up')).not.toBeInTheDocument()
  })

  it('shows at most 4 toasts (oldest dropped)', () => {
    renderToasts()
    for (let i = 0; i < 6; i++) fireEvent.click(screen.getByText('info'))

    expect(screen.getAllByText('Heads up')).toHaveLength(4)
  })

  it('useToast outside the provider throws a clear error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Buttons />)).toThrow('useToast must be used inside <ToastProvider>')
    spy.mockRestore()
  })
})
