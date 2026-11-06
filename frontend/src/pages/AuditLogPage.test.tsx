import { render, screen, within } from '@testing-library/react'
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
import type { AuditLogEntry } from '../types/alerts'
import AuditLogPage from './AuditLogPage'

vi.mock('../api/alertsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/alertsApi')>()),
  listAuditLogs: vi.fn(),
  getAlertSummary: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(alertsApi)

const ENTRIES: AuditLogEntry[] = [
  {
    id: 3,
    created_at: '2026-11-05T12:00:00Z',
    actor_id: 2,
    actor_email: 'manager@example.com',
    action: 'update',
    entity_type: 'product',
    entity_id: 7,
    summary: null,
    changes: {
      unit_price: { old: '100.00', new: '129.90' },
      description: { old: 'Old text', new: null },
    },
  },
  {
    id: 2,
    created_at: '2026-11-05T11:00:00Z',
    actor_id: 3,
    actor_email: 'staff@example.com',
    action: 'inventory.receive',
    entity_type: 'inventory',
    entity_id: 12,
    summary: 'Received 4 x LAP-001 into WH01-ZA-R01-S01-B01',
    changes: { quantity_on_hand: { old: 0, new: 4 } },
  },
  {
    id: 1,
    created_at: '2026-11-05T10:00:00Z',
    actor_id: null,
    actor_email: null,
    action: 'create',
    entity_type: 'user',
    entity_id: 4,
    summary: null,
    changes: { email: { new: 'new@example.com' }, roles: { new: ['manager', 'staff'] } },
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.listAuditLogs.mockResolvedValue(page(ENTRIES, 3, 0, 50))
  api.getAlertSummary.mockResolvedValue({ unresolved: 0 })
})

const row = (text: string) => screen.getByText(text).closest('tr') as HTMLElement

describe('AuditLogPage', () => {
  it('lists who changed what, with the old and new values', async () => {
    renderWithAuth(<AuditLogPage />, { auth: loggedInAs('admin'), path: '/audit-log' })

    await screen.findByText('manager@example.com')
    const update = within(row('manager@example.com'))
    expect(update.getByText('product #7')).toBeInTheDocument()
    expect(update.getByText('2 fields')).toBeInTheDocument()
    expect(update.getByText('unit_price: 100.00 → 129.90')).toBeInTheDocument()
    expect(update.getByText('description: Old text → ∅')).toBeInTheDocument()

    const receive = within(row('staff@example.com'))
    expect(receive.getByText('Received 4 x LAP-001 into WH01-ZA-R01-S01-B01')).toBeInTheDocument()
    expect(receive.getByText('quantity_on_hand: 0 → 4')).toBeInTheDocument()

    const created = within(row('System'))
    expect(created.getByText('roles: manager, staff')).toBeInTheDocument()
  })

  it('filters by record type and action', async () => {
    const user = userEvent.setup()
    renderWithAuth(<AuditLogPage />, {
      auth: loggedInAs('admin'),
      path: '/audit-log?entity=product',
      route: '/audit-log',
    })

    await screen.findByText('manager@example.com')
    expect(api.listAuditLogs).toHaveBeenLastCalledWith({
      entityType: 'product',
      action: undefined,
      offset: 0,
      limit: 50,
    })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Action' }), 'inventory.receive')
    expect(screen.getByTestId('location').textContent).toBe(
      '/audit-log?entity=product&action=inventory.receive',
    )
  })

  it.each(['manager', 'staff', 'customer'] as const)('is forbidden for %s', async (role) => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs(role)}>
          <MemoryRouter initialEntries={['/audit-log']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )

    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listAuditLogs).not.toHaveBeenCalled()
  })
})
