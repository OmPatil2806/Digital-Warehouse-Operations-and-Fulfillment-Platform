import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from './api/healthApi'
import App from './App'
import { makeHealthResponse } from './test/fixtures'

// Replace the real API call with a mock, so tests never need a running backend.
vi.mock('./api/healthApi', () => ({ getHealth: vi.fn() }))
const mockedGetHealth = vi.mocked(getHealth)

const networkError = () => new AxiosError('Network Error', 'ERR_NETWORK')

describe('App health status', () => {
  beforeEach(() => {
    mockedGetHealth.mockReset()
  })

  it('shows "Checking…" while the request is pending', () => {
    mockedGetHealth.mockReturnValue(new Promise(() => {})) // never resolves

    render(<App />)

    expect(screen.getByTestId('backend-status')).toHaveTextContent('Checking…')
    expect(screen.getByRole('button', { name: 'Check again' })).toBeDisabled()
  })

  it('shows "Online" with details when the API is healthy', async () => {
    mockedGetHealth.mockResolvedValue(makeHealthResponse())

    render(<App />)

    expect(await screen.findByText('Online')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('0.1.0')).toBeInTheDocument()
    expect(screen.getByText('test')).toBeInTheDocument()
    expect(mockedGetHealth).toHaveBeenCalledTimes(1)
  })

  it('shows "Degraded" when the API is up but the database is unavailable', async () => {
    mockedGetHealth.mockResolvedValue(
      makeHealthResponse({ status: 'degraded', database: 'unavailable' }),
    )

    render(<App />)

    expect(await screen.findByText('Degraded')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })

  it('shows "Offline" with a helpful message when the API cannot be reached', async () => {
    mockedGetHealth.mockRejectedValue(networkError())

    render(<App />)

    expect(await screen.findByText('Offline')).toBeInTheDocument()
    expect(screen.getByText(/Cannot reach the server/)).toBeInTheDocument()
  })

  it('checks again when "Check again" is clicked', async () => {
    const user = userEvent.setup()
    mockedGetHealth
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce(makeHealthResponse())

    render(<App />)
    expect(await screen.findByText('Offline')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Check again' }))

    expect(await screen.findByText('Online')).toBeInTheDocument()
    expect(mockedGetHealth).toHaveBeenCalledTimes(2)
  })
})
