import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as ordersApi from '../api/ordersApi'
import { makeOrder, makeShipment } from '../test/orderFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { Order } from '../types/orders'
import OrderDetailPage from './OrderDetailPage'

vi.mock('../api/ordersApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/ordersApi')>()),
  getOrder: vi.fn(),
  orderAction: vi.fn(),
  allocateOrder: vi.fn(),
  getOrderShipment: vi.fn(),
}))
const api = vi.mocked(ordersApi)

beforeEach(() => {
  vi.clearAllMocks()
  api.getOrder.mockResolvedValue(makeOrder())
  api.orderAction.mockImplementation(async (_id, action) =>
    makeOrder({
      status:
        action === 'confirm' ? 'inventory_reserved' : action === 'cancel' ? 'cancelled' : 'on_hold',
    }),
  )
  api.allocateOrder.mockResolvedValue([{}, {}])
  api.getOrderShipment.mockResolvedValue(makeShipment())
})

function renderPage(role: Role = 'manager', order?: Partial<Order>) {
  if (order) api.getOrder.mockResolvedValue(makeOrder(order))
  renderWithAuth(<OrderDetailPage />, {
    auth: loggedInAs(role),
    path: '/orders/1',
    route: '/orders/:orderId',
  })
  return userEvent.setup()
}

const button = (name: string) => screen.queryByRole('button', { name })

describe('OrderDetailPage', () => {
  it('shows the order, its lines, address and timeline', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Order SO-2026-000001' })).toBeInTheDocument()
    expect(screen.getByText('Chris Customer (CUST-0001)')).toBeInTheDocument()
    const lines = screen.getByRole('table', { name: 'Order lines' })
    expect(within(lines).getByText('LAP-1401')).toBeInTheDocument()
    expect(within(lines).getByText('€1,798.00')).toBeInTheDocument()
    expect(screen.getByText('70178 Stuttgart')).toBeInTheDocument()
    const timeline = screen.getByRole('list', { name: 'Status timeline' })
    expect(within(timeline).getByText('Created')).toBeInTheDocument()
    expect(within(timeline).getByText(/Maya Manager/)).toBeInTheDocument()
  })

  it('managers confirm, hold and cancel a new order', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Confirm order' }))
    await waitFor(() => expect(api.orderAction).toHaveBeenCalledWith(1, 'confirm', undefined))
    expect(await screen.findByRole('status')).toHaveTextContent('SO-2026-000001: Reserved')

    await user.click(screen.getByRole('button', { name: 'Cancel order' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Cancel SO-2026-000001?' }))
    await user.click(dialog.getByRole('button', { name: 'Cancel order' }))
    expect(dialog.getByText('Write at least 3 characters')).toBeInTheDocument()
    await user.type(dialog.getByRole('textbox'), 'Customer phoned')
    await user.click(dialog.getByRole('button', { name: 'Cancel order' }))
    await waitFor(() =>
      expect(api.orderAction).toHaveBeenCalledWith(1, 'cancel', 'Customer phoned'),
    )
    expect(button('Put on hold')).toBeInTheDocument()
  })

  it('customers confirm or cancel their order but cannot hold it; no names in the timeline', async () => {
    renderPage('customer')

    await screen.findByRole('heading', { name: 'Order SO-2026-000001' })
    expect(button('Confirm order')).toBeInTheDocument()
    expect(button('Cancel order')).toBeInTheDocument()
    expect(button('Put on hold')).not.toBeInTheDocument()
    expect(screen.queryByText(/Maya Manager/)).not.toBeInTheDocument()
  })

  it('staff create the picking route of a reserved order and nothing else', async () => {
    const user = renderPage('staff', {
      status: 'inventory_reserved',
      next_statuses: ['allocated', 'on_hold', 'cancelled'],
    })

    await user.click(await screen.findByRole('button', { name: 'Create picking route' }))
    await waitFor(() => expect(api.allocateOrder).toHaveBeenCalled())
    expect(await screen.findByRole('status')).toHaveTextContent('Picking route created (2 task(s))')
    expect(button('Cancel order')).not.toBeInTheDocument()
    expect(button('Put on hold')).not.toBeInTheDocument()
  })

  it('backordered orders explain the wait and offer a retry to managers', async () => {
    const user = renderPage('manager', {
      status: 'backordered',
      next_statuses: ['inventory_reserved', 'partially_allocated', 'on_hold', 'cancelled'],
    })

    expect(
      await screen.findByText(/reserved automatically as soon as goods arrive/),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry reservation' }))
    await waitFor(() => expect(api.orderAction).toHaveBeenCalledWith(1, 'reserve', undefined))
  })

  it('shows the shipment with tracking link and events once shipped', async () => {
    renderPage('customer', { status: 'shipped', next_statuses: ['delivered', 'delayed'] })

    const shipment = await screen.findByRole('region', { name: 'Shipment' })
    expect(within(shipment).getByText('DHL261106000001')).toBeInTheDocument()
    expect(within(shipment).getByRole('link', { name: /Track with DHL Paket/ })).toHaveAttribute(
      'href',
      'https://track.example.com/DHL261106000001',
    )
    const events = within(shipment).getByRole('list', { name: 'Tracking events' })
    expect(within(events).getByText('in transit')).toBeInTheDocument()
    expect(within(events).getByText('DHL hub Stuttgart')).toBeInTheDocument()
    expect(button('Cancel order')).not.toBeInTheDocument()
  })

  it('an unknown or foreign order shows "not found"', async () => {
    const response = {
      status: 404,
      data: { detail: 'Order not found' },
      statusText: '',
      headers: {},
      config: { headers: new AxiosHeaders() },
    } as AxiosResponse
    api.getOrder.mockRejectedValue(new AxiosError('x', 'ERR', undefined, undefined, response))
    renderPage('customer')

    expect(await screen.findByRole('heading', { name: /not found/i })).toBeInTheDocument()
  })
})
