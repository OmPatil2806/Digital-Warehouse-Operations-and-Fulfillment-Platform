import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as fulfillmentApi from '../api/fulfillmentApi'
import { page } from '../test/catalogFixtures'
import { makeShipment } from '../test/orderFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { OrderReturn } from '../types/orders'
import ShipmentsPage from './ShipmentsPage'

vi.mock('../api/fulfillmentApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/fulfillmentApi')>()),
  listShipments: vi.fn(),
  addShipmentEvent: vi.fn(),
  checkDelays: vi.fn(),
  listReturns: vi.fn(),
  inspectReturn: vi.fn(),
  cancelReturn: vi.fn(),
}))
const api = vi.mocked(fulfillmentApi)

const RETURN: OrderReturn = {
  id: 5,
  return_number: 'RT-2026-000001',
  order_id: 1,
  order_number: 'SO-2026-000001',
  status: 'open',
  reason: 'Does not fit',
  created_at: '2026-11-06T12:00:00Z',
  completed_at: null,
  items: [
    {
      id: 1,
      product: { id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' },
      quantity: 1,
      condition: null,
      bin: null,
      note: null,
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listShipments.mockResolvedValue(
    page([
      makeShipment(),
      makeShipment({ id: 4, tracking_number: 'DPD123456', status: 'delayed' }),
    ]),
  )
  api.addShipmentEvent.mockImplementation(async () =>
    makeShipment({
      status: 'delivered',
      delivered_at: '2026-11-07T10:00:00Z',
      events: [
        ...makeShipment().events,
        {
          id: 9,
          event_type: 'delivered',
          occurred_at: '2026-11-07T10:00:00Z',
          location: 'Reception',
          description: null,
        },
      ],
    }),
  )
  api.checkDelays.mockResolvedValue([makeShipment()])
  api.listReturns.mockResolvedValue(page([RETURN]))
  api.inspectReturn.mockResolvedValue({ ...RETURN, status: 'completed' })
  api.cancelReturn.mockResolvedValue({ ...RETURN, status: 'cancelled' })
})

function renderPage(role: Role = 'staff', path = '/shipments') {
  renderWithAuth(<ShipmentsPage />, { auth: loggedInAs(role), path, route: '/shipments' })
  return userEvent.setup()
}

describe('ShipmentsPage', () => {
  it('lists shipments; staff add tracking updates', async () => {
    const user = renderPage()

    await user.click(await screen.findByText('DHL261106000001'))
    const dialog = within(screen.getByRole('dialog', { name: 'Shipment DHL261106000001' }))
    const events = dialog.getByRole('list', { name: 'Tracking events' })
    expect(within(events).getByText('In transit')).toBeInTheDocument()

    await user.selectOptions(dialog.getByRole('combobox', { name: 'What happened?' }), 'exception')
    await user.click(dialog.getByRole('button', { name: 'Add update' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Describe the exception')

    await user.selectOptions(dialog.getByRole('combobox', { name: 'What happened?' }), 'delivered')
    await user.type(dialog.getByRole('textbox', { name: 'Where' }), 'Reception')
    await user.click(dialog.getByRole('button', { name: 'Add update' }))
    await waitFor(() =>
      expect(api.addShipmentEvent).toHaveBeenCalledWith(3, {
        event_type: 'delivered',
        location: 'Reception',
        description: undefined,
      }),
    )
    const updated = dialog.getByRole('list', { name: 'Tracking events' })
    expect(await within(updated).findByText('Delivered')).toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: 'Add update' })).not.toBeInTheDocument()
  })

  it('customers see their shipments but cannot add updates or check delays', async () => {
    const user = renderPage('customer')

    expect(await screen.findByRole('heading', { name: 'My shipments' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check delays' })).not.toBeInTheDocument()
    await user.click(await screen.findByText('DHL261106000001'))
    expect(screen.queryByRole('button', { name: 'Add update' })).not.toBeInTheDocument()
  })

  it('managers check for delays', async () => {
    const user = renderPage('manager')

    await user.click(await screen.findByRole('button', { name: 'Check delays' }))
    expect(await screen.findByRole('status')).toHaveTextContent('1 shipment(s) marked as delayed')
  })

  it('filters by status through the URL', async () => {
    renderPage('staff', '/shipments?status=delayed')

    await screen.findByText('DPD123456')
    expect(api.listShipments).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'delayed' }),
    )
  })
})

describe('ShipmentsPage – returns', () => {
  it('staff inspect a return as damaged', async () => {
    const user = renderPage('staff', '/shipments?view=returns')

    await user.click(await screen.findByRole('button', { name: 'Inspect RT-2026-000001' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Inspect return RT-2026-000001' }))
    await user.selectOptions(
      dialog.getByRole('combobox', { name: 'Condition of ACC-MOU1' }),
      'damaged',
    )
    await user.type(dialog.getByRole('textbox', { name: 'Note' }), 'Scroll wheel broken')
    await user.click(dialog.getByRole('button', { name: 'Book into stock' }))

    await waitFor(() =>
      expect(api.inspectReturn).toHaveBeenCalledWith(5, [
        { product_id: 8, condition: 'damaged', note: 'Scroll wheel broken' },
      ]),
    )
    expect(screen.queryByRole('button', { name: 'Cancel RT-2026-000001' })).not.toBeInTheDocument()
  })

  it('customers cancel their open return but cannot inspect it', async () => {
    const user = renderPage('customer', '/shipments?view=returns')

    await user.click(await screen.findByRole('button', { name: 'Cancel RT-2026-000001' }))
    await waitFor(() => expect(api.cancelReturn).toHaveBeenCalledWith(5, expect.anything()))
    expect(screen.queryByRole('button', { name: 'Inspect RT-2026-000001' })).not.toBeInTheDocument()
  })
})
