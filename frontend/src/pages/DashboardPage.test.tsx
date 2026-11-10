import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../api/healthApi'
import { makeHealthResponse } from '../test/fixtures'
import { makeAuth, makeUser, renderWithAuth } from '../test/renderWithAuth'
import DashboardPage from './DashboardPage'

// Replace the real API call with a mock, so tests never need a running backend.
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
// The role dashboards are tested in DashboardPage.roles.test.tsx; here they stay loading.
const { pending } = vi.hoisted(() => ({ pending: () => new Promise(() => {}) }))
vi.mock('../api/dashboardApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/dashboardApi')>()),
  getOverviewDashboard: pending,
  getFulfillmentDashboard: pending,
  getInventoryDashboard: pending,
}))
vi.mock('../api/alertsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/alertsApi')>()),
  listAlerts: pending,
}))

const auth = makeAuth({
  status: 'authenticated',
  user: makeUser({ full_name: 'Maya Manager', roles: ['manager', 'staff'] }),
})

function renderPage() {
  return renderWithAuth(<DashboardPage />, { auth })
}
const mockedGetHealth = vi.mocked(getHealth)

const networkError = () => new AxiosError('Network Error', 'ERR_NETWORK')

describe('DashboardPage', () => {
  beforeEach(() => {
    mockedGetHealth.mockReset()
  })

  it('greets the user and lists only the modules for their roles', () => {
    mockedGetHealth.mockResolvedValue(makeHealthResponse())

    renderPage()

    expect(screen.getByRole('heading', { name: 'Welcome, Maya Manager' })).toBeInTheDocument()
    const modules = screen.getByRole('region', { name: 'Your modules' })
    expect(modules).toHaveTextContent('Products')
    expect(modules).toHaveTextContent('Suppliers') // manager-only
    expect(modules).not.toHaveTextContent('Users') // admin-only
    expect(modules).toHaveTextContent('Inventory')
    expect(modules).toHaveTextContent('Shipments')
    expect(modules).toHaveTextContent('Phase 9')
  })

  it('shows "Checking…" while the request is pending', () => {
    mockedGetHealth.mockReturnValue(new Promise(() => {})) // never resolves

    renderPage()

    expect(screen.getByTestId('backend-status')).toHaveTextContent('Checking…')
    expect(screen.getByRole('button', { name: 'Check again' })).toBeDisabled()
  })

  it('shows "Online" with details when the API is healthy', async () => {
    mockedGetHealth.mockResolvedValue(makeHealthResponse())

    renderPage()

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

    renderPage()

    expect(await screen.findByText('Degraded')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })

  it('shows "Offline" with a helpful message when the API cannot be reached', async () => {
    mockedGetHealth.mockRejectedValue(networkError())

    renderPage()

    expect(await screen.findByText('Offline')).toBeInTheDocument()
    expect(screen.getByText(/Cannot reach the server/)).toBeInTheDocument()
  })

  it('checks again when "Check again" is clicked', async () => {
    const user = userEvent.setup()
    mockedGetHealth
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce(makeHealthResponse())

    renderPage()
    expect(await screen.findByText('Offline')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Check again' }))

    expect(await screen.findByText('Online')).toBeInTheDocument()
    expect(mockedGetHealth).toHaveBeenCalledTimes(2)
  })
})
