import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as inventoryApi from '../../api/inventoryApi'
import { loggedInAs, makeAuth, makeUser, renderWithAuth } from '../../test/renderWithAuth'
import type { StockAdjustment, StockTransfer } from '../../types/inventory'
import { RequestsPanel } from './RequestsPanel'

vi.mock('../../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/inventoryApi')>()),
  getApprovalQueue: vi.fn(),
  listMyRequests: vi.fn(),
  decideRequest: vi.fn(),
}))
const api = vi.mocked(inventoryApi)

const SAM = { id: 3, full_name: 'Sam Staff', email: 'staff@example.com' }
const product = { id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' }
const base = {
  created_at: '2026-11-05T10:00:00Z',
  status: 'pending' as const,
  product,
  quantity: 2,
  requested_by: SAM,
  decided_by: null,
  decided_at: null,
  decision_note: null,
}
const ADJUSTMENT: StockAdjustment = {
  ...base,
  id: 6,
  kind: 'decrease',
  bin: { id: 30, location_code: 'WH01-ZA-R08-S04-B06' },
  reason: 'Two missing',
}
const TRANSFER: StockTransfer = {
  ...base,
  id: 9,
  created_at: '2026-11-05T11:00:00Z',
  from_bin: { id: 30, location_code: 'WH01-ZA-R08-S04-B06' },
  to_bin: { id: 99, location_code: 'WH02-ZA-R01-S01-B01' },
  reason: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getApprovalQueue.mockResolvedValue({ adjustments: [ADJUSTMENT], transfers: [TRANSFER] })
  api.listMyRequests.mockResolvedValue({
    adjustments: [
      ADJUSTMENT,
      { ...ADJUSTMENT, id: 5, status: 'rejected', decision_note: 'Found them' },
    ],
    transfers: [],
  })
  api.decideRequest.mockImplementation(async (_kind, id, action) => ({
    id,
    status: action === 'approve' ? 'completed' : action === 'reject' ? 'rejected' : 'cancelled',
  }))
})

const row = (text: string) => screen.getByText(text).closest('tr') as HTMLElement

describe('RequestsPanel for managers', () => {
  it('lists adjustments and transfers waiting for approval', async () => {
    renderWithAuth(<RequestsPanel />, { auth: loggedInAs('manager') })

    const table = await screen.findByRole('table', { name: 'Requests waiting for approval' })
    await within(table).findByText('Missing units (decrease): 2 × ACC-MOU1')
    expect(within(table).getByText('Transfer: 2 × ACC-MOU1')).toBeInTheDocument()
    expect(within(table).getByText('WH01-ZA-R08-S04-B06 → WH02-ZA-R01-S01-B01')).toBeInTheDocument()
    expect(within(table).getAllByText('by Sam Staff')).toHaveLength(2)
    expect(api.listMyRequests).not.toHaveBeenCalled()
  })

  it('approves directly and rejects with a required note', async () => {
    const user = userEvent.setup()
    renderWithAuth(<RequestsPanel />, { auth: loggedInAs('manager') })

    await user.click(await screen.findByRole('button', { name: 'Approve request 6' }))
    await waitFor(() =>
      expect(api.decideRequest).toHaveBeenCalledWith('adjustments', 6, 'approve', undefined),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Adjustment #6 approved and applied',
    )

    await user.click(screen.getByRole('button', { name: 'Reject request 9' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Reject request 9' }))
    await user.click(dialog.getByRole('button', { name: 'Reject' }))
    expect(dialog.getByText('Write at least 3 characters')).toBeInTheDocument()
    await user.type(dialog.getByRole('textbox', { name: /Why is it rejected/ }), 'Not needed')
    await user.click(dialog.getByRole('button', { name: 'Reject' }))
    await waitFor(() =>
      expect(api.decideRequest).toHaveBeenCalledWith('transfers', 9, 'reject', 'Not needed'),
    )
  })

  it('cannot approve their own request', async () => {
    const auth = makeAuth({
      status: 'authenticated',
      user: makeUser({ id: 3, roles: ['manager', 'staff'] }),
    })
    renderWithAuth(<RequestsPanel />, { auth })

    expect(await screen.findByRole('button', { name: 'Approve request 6' })).toBeDisabled()
  })
})

describe('RequestsPanel for staff', () => {
  it('shows their own requests and lets them cancel pending ones', async () => {
    const user = userEvent.setup()
    renderWithAuth(<RequestsPanel />, { auth: loggedInAs('staff') })

    await screen.findByRole('table', { name: 'My requests' })
    expect(await screen.findByText('Manager: Found them')).toBeInTheDocument()
    expect(within(row('Manager: Found them')).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
    expect(api.getApprovalQueue).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Cancel request 6' }))
    await waitFor(() =>
      expect(api.decideRequest).toHaveBeenCalledWith('adjustments', 6, 'cancel', undefined),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Adjustment #6 cancelled')
  })
})
