import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as alertsApi from '../api/alertsApi'
import { getHealth } from '../api/healthApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { page } from '../test/catalogFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import type { Role } from '../types/auth'
import type { Alert } from '../types/alerts'
import AlertsPage from './AlertsPage'

vi.mock('../api/alertsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/alertsApi')>()),
  listAlerts: vi.fn(),
  getAlertSummary: vi.fn(),
  acknowledgeAlert: vi.fn(),
  resolveAlert: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(alertsApi)

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    created_at: '2026-11-05T10:00:00Z',
    updated_at: '2026-11-05T10:00:00Z',
    alert_type: 'low_stock',
    severity: 'warning',
    status: 'open',
    title: 'Low stock: LAP-1601',
    message: 'Laptop 16" Creator: 1 available, minimum stock is 2.',
    product: { id: 4, sku: 'LAP-1601', name: 'Laptop 16" Creator' },
    bin: null,
    acknowledged_by: null,
    acknowledged_at: null,
    resolved_by: null,
    resolved_at: null,
    ...overrides,
  }
}

const ALERTS = [
  makeAlert(),
  makeAlert({
    id: 2,
    severity: 'critical',
    title: 'Low stock: TOO-LAD1',
    message: '0 available',
    product: { id: 9, sku: 'TOO-LAD1', name: 'Ladder' },
    status: 'acknowledged',
    acknowledged_by: { id: 2, full_name: 'Maya Manager', email: 'manager@example.com' },
  }),
  makeAlert({
    id: 3,
    alert_type: 'over_capacity',
    title: 'Bin over capacity: WH01-ZA-R01-S01-B01',
    product: null,
    bin: { id: 20, location_code: 'WH01-ZA-R01-S01-B01' },
    status: 'resolved',
  }),
]

beforeEach(() => {
  vi.clearAllMocks()
  api.listAlerts.mockResolvedValue(page(ALERTS))
  api.getAlertSummary.mockResolvedValue({ unresolved: 2 })
  api.acknowledgeAlert.mockImplementation(async (id) => ({
    ...ALERTS[0],
    id,
    status: 'acknowledged',
  }))
  api.resolveAlert.mockImplementation(async (id) => ({ ...ALERTS[0], id, status: 'resolved' }))
})

function renderPage(role: Role = 'manager', path = '/alerts') {
  renderWithAuth(<AlertsPage />, { auth: loggedInAs(role), path, route: '/alerts' })
  return userEvent.setup()
}

const row = (text: string) => screen.getByText(text).closest('tr') as HTMLElement
const location = () => screen.getByTestId('location').textContent

describe('AlertsPage', () => {
  it('shows what needs attention by default, with severity, subject and status', async () => {
    renderPage()

    await screen.findByText('Low stock: LAP-1601')
    expect(api.listAlerts).toHaveBeenLastCalledWith({
      status: 'unresolved',
      alertType: undefined,
      offset: 0,
      limit: 25,
    })
    const ladder = within(row('Low stock: TOO-LAD1'))
    expect(ladder.getByText('critical')).toBeInTheDocument()
    expect(ladder.getByText('Acknowledged by Maya Manager')).toBeInTheDocument()
    expect(
      within(row('Low stock: LAP-1601')).getByRole('link', { name: 'LAP-1601' }),
    ).toHaveAttribute('href', '/inventory?product=4')
    const bin = within(row('Bin over capacity: WH01-ZA-R01-S01-B01'))
    expect(bin.getByText('Resolved automatically')).toBeInTheDocument()
    expect(bin.queryByRole('button')).not.toBeInTheDocument()
  })

  it('managers acknowledge and resolve', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Acknowledge Low stock: LAP-1601' }))
    await waitFor(() => expect(api.acknowledgeAlert).toHaveBeenCalledWith(1))
    // already acknowledged: only Resolve is offered
    expect(
      screen.queryByRole('button', { name: 'Acknowledge Low stock: TOO-LAD1' }),
    ).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Resolve Low stock: TOO-LAD1' }))
    await waitFor(() => expect(api.resolveAlert).toHaveBeenCalledWith(2))
  })

  it('staff can read alerts but not handle them', async () => {
    renderPage('staff')

    await screen.findByText('Low stock: LAP-1601')
    expect(screen.queryByRole('button', { name: /Acknowledge|Resolve/ })).not.toBeInTheDocument()
  })

  it('filters by status and type through the URL', async () => {
    const user = renderPage('manager', '/alerts?status=resolved&type=over_capacity')

    await screen.findByText('Low stock: LAP-1601')
    expect(api.listAlerts).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'resolved', alertType: 'over_capacity' }),
    )
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status' }), 'Needs attention')
    expect(location()).toBe('/alerts?type=over_capacity')
  })
})

describe('/alerts route', () => {
  it('is not available to customers', async () => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs('customer')}>
          <MemoryRouter initialEntries={['/alerts']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )

    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listAlerts).not.toHaveBeenCalled()
  })
})
