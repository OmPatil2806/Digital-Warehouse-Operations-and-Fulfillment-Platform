import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import { getHealth } from '../api/healthApi'
import * as inventoryApi from '../api/inventoryApi'
import * as ordersApi from '../api/ordersApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { makeProduct, page } from '../test/catalogFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { makeProductStock } from '../test/inventoryFixtures'
import { makeCustomer, makeOrder, makeOrderSummary } from '../test/orderFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import type { Role } from '../types/auth'
import OrdersPage from './OrdersPage'

vi.mock('../api/ordersApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/ordersApi')>()),
  listOrders: vi.fn(),
  createOrder: vi.fn(),
  listCustomers: vi.fn(),
  getMyCustomer: vi.fn(),
}))
vi.mock('../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/catalogApi')>()),
  listProducts: vi.fn(),
}))
vi.mock('../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/inventoryApi')>()),
  getProductStock: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(ordersApi)

const ACME = makeCustomer({
  id: 2,
  code: 'CUST-0002',
  name: 'Acme GmbH',
  city: 'Esslingen',
  user_id: null,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listOrders.mockResolvedValue(
    page([
      makeOrderSummary(),
      makeOrderSummary({
        id: 2,
        order_number: 'SO-2026-000002',
        customer: { id: 2, code: 'CUST-0002', name: 'Acme GmbH' },
        status: 'delayed',
        priority: 'urgent',
      }),
    ]),
  )
  api.listCustomers.mockResolvedValue(page([makeCustomer(), ACME]))
  api.getMyCustomer.mockResolvedValue(makeCustomer())
  api.createOrder.mockResolvedValue(makeOrder({ id: 9, order_number: 'SO-2026-000009' }))
  vi.mocked(catalogApi.listProducts).mockResolvedValue(page([makeProduct()]))
  vi.mocked(inventoryApi.getProductStock).mockResolvedValue(
    makeProductStock({ quantity_available: 3 }),
  )
})

function renderPage(role: Role = 'manager', path = '/orders') {
  renderWithAuth(<OrdersPage />, {
    auth: loggedInAs(role),
    path,
    route: '/orders',
    routes: { '/orders/:orderId': <p>order detail page</p> },
  })
  return userEvent.setup()
}

const row = (text: string) => screen.getByText(text).closest('tr') as HTMLElement

describe('OrdersPage', () => {
  it('lists orders with customer, status and priority', async () => {
    renderPage()

    await screen.findByText('SO-2026-000002')
    const delayed = within(row('SO-2026-000002'))
    expect(delayed.getByText('Acme GmbH')).toBeInTheDocument()
    expect(delayed.getByText('Delayed')).toBeInTheDocument()
    expect(delayed.getByText('urgent')).toBeInTheDocument()
    expect(within(row('SO-2026-000001')).getByText('€1,872.70')).toBeInTheDocument()
  })

  it('customers see "My orders" without the customer column', async () => {
    renderPage('customer')

    expect(await screen.findByRole('heading', { name: 'My orders' })).toBeInTheDocument()
    await screen.findByText('SO-2026-000001')
    expect(screen.queryByRole('columnheader', { name: 'Customer' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New order' })).toBeInTheDocument()
  })

  it('staff cannot place orders', async () => {
    renderPage('staff')
    await screen.findByText('SO-2026-000001')
    expect(screen.queryByRole('button', { name: 'New order' })).not.toBeInTheDocument()
  })

  it('filters by status through the URL and opens an order', async () => {
    const user = renderPage('manager', '/orders?status=delayed')

    await screen.findByText('SO-2026-000002')
    expect(api.listOrders).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'delayed', offset: 0 }),
    )
    await user.click(screen.getByText('SO-2026-000002'))
    expect(await screen.findByText('order detail page')).toBeInTheDocument()
  })
})

describe('New order', () => {
  async function open(role: Role) {
    const user = renderPage(role)
    await user.click(await screen.findByRole('button', { name: 'New order' }))
    return { user, dialog: within(screen.getByRole('dialog', { name: 'New order' })) }
  }

  async function addLaptop(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByPlaceholderText('Type a SKU or name'), 'lap')
    await user.click(await screen.findByRole('button', { name: /LAP-1401/ }))
  }

  it('managers choose the customer, see availability and place the order', async () => {
    const { user, dialog } = await open('manager')

    await user.click(dialog.getByRole('button', { name: 'Place order' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Choose a customer')

    await waitFor(() =>
      expect(
        dialog.getByRole('option', { name: 'CUST-0002 · Acme GmbH (Esslingen)' }),
      ).toBeInTheDocument(),
    )
    await user.selectOptions(dialog.getByRole('combobox', { name: /Customer/ }), '2')
    await addLaptop(user)
    const quantity = dialog.getByRole('textbox', { name: 'Quantity of LAP-1401' })
    await user.clear(quantity)
    await user.type(quantity, '5')
    expect(
      await dialog.findByText('3 available — the rest will be backordered'),
    ).toBeInTheDocument()
    await user.selectOptions(dialog.getByRole('combobox', { name: 'Priority' }), 'high')
    await user.click(dialog.getByRole('button', { name: 'Place order' }))

    await waitFor(() =>
      expect(api.createOrder).toHaveBeenCalledWith(
        {
          customer_id: 2,
          items: [{ product_id: 7, quantity: 5 }],
          priority: 'high',
          requested_delivery_date: undefined,
          notes: undefined,
        },
        expect.anything(),
      ),
    )
    expect(await screen.findByText('order detail page')).toBeInTheDocument()
  })

  it('customers order for themselves, without priority or stock figures', async () => {
    const { user, dialog } = await open('customer')

    expect(await dialog.findByText('Chris Customer (CUST-0001)')).toBeInTheDocument()
    expect(dialog.queryByRole('combobox', { name: /Customer/ })).not.toBeInTheDocument()
    expect(dialog.queryByRole('combobox', { name: 'Priority' })).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Place order' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Add at least one product')

    await addLaptop(user)
    expect(dialog.queryByText(/available/)).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Remove LAP-1401' }))
    await addLaptop(user)
    await user.click(dialog.getByRole('button', { name: 'Place order' }))

    await waitFor(() =>
      expect(api.createOrder).toHaveBeenCalledWith(
        expect.objectContaining({ customer_id: 1, priority: undefined }),
        expect.anything(),
      ),
    )
    expect(inventoryApi.getProductStock).not.toHaveBeenCalled()
  })
})

describe('/orders route', () => {
  it('is open to customers', async () => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs('customer')}>
          <MemoryRouter initialEntries={['/orders']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )
    expect(await screen.findByRole('heading', { name: 'My orders' })).toBeInTheDocument()
  })
})
