import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import * as inventoryApi from '../api/inventoryApi'
import { productPage } from '../test/opsMocks'
import { makeAuth, makeUser, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { CycleCount } from '../types/inventory'
import CycleCountPage from './CycleCountPage'

vi.mock('../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/inventoryApi')>()),
  getCycleCount: vi.fn(),
  recordCounts: vi.fn(),
  cycleCountAction: vi.fn(),
}))
vi.mock('../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/catalogApi')>()),
  listProducts: vi.fn(),
}))
const api = vi.mocked(inventoryApi)

const SAM = { id: 3, full_name: 'Sam Staff', email: 'staff@example.com' }
function makeCount(overrides: Partial<CycleCount> = {}): CycleCount {
  return {
    id: 4,
    created_at: '2026-11-05T10:00:00Z',
    status: 'open',
    bin: { id: 20, location_code: 'WH01-ZA-R01-S01-B01' },
    requested_by: SAM,
    submitted_at: null,
    note: 'Weekly',
    decided_by: null,
    decided_at: null,
    decision_note: null,
    lines: [
      {
        id: 1,
        product: { id: 7, sku: 'LAP-1401', name: 'Laptop 14" Business' },
        expected_quantity: 16,
        counted_quantity: null,
        variance: null,
      },
    ],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getCycleCount.mockResolvedValue(makeCount())
  api.recordCounts.mockImplementation(async () => makeCount())
  api.cycleCountAction.mockImplementation(async (_id, action) =>
    makeCount({
      status: action === 'submit' ? 'submitted' : action === 'approve' ? 'completed' : 'open',
    }),
  )
  vi.mocked(catalogApi.listProducts).mockResolvedValue(productPage)
})

function renderPage(role: Role = 'staff', userId = 3) {
  renderWithAuth(<CycleCountPage />, {
    auth: makeAuth({ status: 'authenticated', user: makeUser({ id: userId, roles: [role] }) }),
    path: '/inventory/cycle-counts/4',
    route: '/inventory/cycle-counts/:countId',
  })
  return userEvent.setup()
}

describe('CycleCountPage', () => {
  it('enters counts with a live difference, adds a found product and submits', async () => {
    const user = renderPage()

    const input = await screen.findByRole('textbox', { name: 'Counted LAP-1401' })
    await user.type(input, '15')
    expect(input.closest('tr')).toHaveTextContent('−1')

    await user.click(screen.getByRole('button', { name: /Add a product found here/ }))
    await user.type(screen.getByPlaceholderText('Type a SKU or name'), 'mou')
    await user.click(await screen.findByRole('button', { name: /ACC-MOU1/ }))
    const found = screen.getByRole('textbox', { name: 'Counted ACC-MOU1' })
    expect(found.closest('tr')).toHaveTextContent('new')

    await user.click(screen.getByRole('button', { name: /Submit for approval/ }))
    expect(screen.getByRole('alert')).toHaveTextContent('ACC-MOU1 is missing')
    expect(api.recordCounts).not.toHaveBeenCalled()

    await user.type(found, '3')
    await user.click(screen.getByRole('button', { name: /Submit for approval/ }))
    await waitFor(() =>
      expect(api.recordCounts).toHaveBeenCalledWith(4, [
        { product_id: 7, counted_quantity: 15 },
        { product_id: 8, counted_quantity: 3 },
      ]),
    )
    await waitFor(() => expect(api.cycleCountAction).toHaveBeenCalledWith(4, 'submit', undefined))
  })

  it('rejects counts that are not whole numbers', async () => {
    const user = renderPage()

    await user.type(await screen.findByRole('textbox', { name: 'Counted LAP-1401' }), '1.5')
    await user.click(screen.getByRole('button', { name: /Save counts/ }))

    expect(screen.getByRole('alert')).toHaveTextContent('LAP-1401: enter a whole number')
    expect(api.recordCounts).not.toHaveBeenCalled()
  })

  it('a manager who did not count approves or sends it back', async () => {
    api.getCycleCount.mockResolvedValue(
      makeCount({
        status: 'submitted',
        submitted_at: '2026-11-05T10:30:00Z',
        lines: [{ ...makeCount().lines[0], counted_quantity: 15, variance: -1 }],
      }),
    )
    const user = renderPage('manager', 2)

    expect(await screen.findByRole('cell', { name: '−1' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Counted/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Send back for recount/ }))
    const dialog = within(screen.getByRole('dialog', { name: 'Send back for a recount' }))
    await user.type(dialog.getByRole('textbox'), 'Count the top shelf again')
    await user.click(dialog.getByRole('button', { name: 'Send back' }))
    await waitFor(() =>
      expect(api.cycleCountAction).toHaveBeenCalledWith(4, 'reject', 'Count the top shelf again'),
    )

    await user.click(screen.getByRole('button', { name: /Approve and correct stock/ }))
    await waitFor(() => expect(api.cycleCountAction).toHaveBeenCalledWith(4, 'approve', undefined))
  })

  it('the person who counted cannot approve it', async () => {
    api.getCycleCount.mockResolvedValue(makeCount({ status: 'submitted' }))
    renderPage('manager', 3) // Sam started this count

    expect(
      await screen.findByText(/another manager or admin has to approve it/),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  })

  it('staff wait for a manager; a completed count shows the decision', async () => {
    api.getCycleCount.mockResolvedValue(makeCount({ status: 'submitted' }))
    renderPage('staff', 5)
    expect(
      await screen.findByText('Waiting for a manager to approve the differences.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cancel count/ })).not.toBeInTheDocument()
  })
})
