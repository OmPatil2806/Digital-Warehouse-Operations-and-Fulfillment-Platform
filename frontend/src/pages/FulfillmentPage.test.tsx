import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as fulfillmentApi from '../api/fulfillmentApi'
import { getHealth } from '../api/healthApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { page } from '../test/catalogFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { makeShipment } from '../test/orderFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import type { PackingTask, PickingTask } from '../types/orders'
import FulfillmentPage from './FulfillmentPage'

vi.mock('../api/fulfillmentApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/fulfillmentApi')>()),
  listPickingTasks: vi.fn(),
  startPicking: vi.fn(),
  completePicking: vi.fn(),
  listPackingTasks: vi.fn(),
  startPacking: vi.fn(),
  completePacking: vi.fn(),
  listCarriers: vi.fn(),
  createShipment: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(fulfillmentApi)

const ORDER = {
  id: 4,
  order_number: 'SO-2026-000004',
  priority: 'urgent' as const,
  status: 'allocated' as const,
}

function makeTask(overrides: Partial<PickingTask> = {}): PickingTask {
  return {
    id: 1,
    order: ORDER,
    sequence: 1,
    product: { id: 7, sku: 'AUT-FIL1', name: 'Oil Filter', barcode: '4000000000017' },
    bin: { id: 20, location_code: 'WH01-ZA-R09-S01-B01' },
    quantity: 4,
    quantity_picked: null,
    status: 'pending',
    assigned_to: null,
    started_at: null,
    completed_at: null,
    short_reason: null,
    ...overrides,
  }
}

function makePacking(overrides: Partial<PackingTask> = {}): PackingTask {
  return {
    id: 9,
    order: { ...ORDER, status: 'picked' },
    status: 'pending',
    packed_by: null,
    started_at: null,
    completed_at: null,
    package_count: null,
    weight_kg: null,
    note: null,
    lines: [
      {
        product: { id: 7, sku: 'AUT-FIL1', name: 'Oil Filter' },
        quantity_ordered: 4,
        quantity_picked: 4,
      },
      {
        product: { id: 8, sku: 'AUT-WIP1', name: 'Wipers' },
        quantity_ordered: 2,
        quantity_picked: 1,
      },
    ],
    ...overrides,
  }
}

const SAM = { id: 3, full_name: 'Sam Staff', email: 'staff@example.com' }

beforeEach(() => {
  vi.clearAllMocks()
  api.listPickingTasks.mockResolvedValue(
    page([makeTask(), makeTask({ id: 2, sequence: 2, status: 'in_progress', assigned_to: SAM })]),
  )
  api.startPicking.mockImplementation(async (id) =>
    makeTask({ id, status: 'in_progress', assigned_to: SAM }),
  )
  api.completePicking.mockImplementation(async (id, input) =>
    makeTask({
      id,
      status: input.quantity_picked < 4 ? 'short' : 'completed',
      quantity_picked: input.quantity_picked,
    }),
  )
  api.listPackingTasks.mockImplementation(async (status = 'open') =>
    status === 'open'
      ? page([makePacking()])
      : page([
          makePacking({
            id: 10,
            order: { id: 5, order_number: 'SO-2026-000005', priority: 'normal', status: 'packed' },
            status: 'completed',
            package_count: 1,
            weight_kg: '2.000',
          }),
        ]),
  )
  api.startPacking.mockImplementation(async (id) => makePacking({ id, status: 'in_progress' }))
  api.completePacking.mockImplementation(async (id) =>
    makePacking({ id, status: 'completed', package_count: 2, weight_kg: '3.5' }),
  )
  api.listCarriers.mockResolvedValue([
    { id: 1, code: 'DHL', name: 'DHL Paket', default_transit_days: 2, is_active: true },
  ])
  api.createShipment.mockResolvedValue(makeShipment())
})

function renderPage(path = '/fulfillment') {
  renderWithAuth(<FulfillmentPage />, { auth: loggedInAs('staff'), path, route: '/fulfillment' })
  return userEvent.setup()
}

describe('FulfillmentPage – picking', () => {
  it('lists open picks with order, stop, bin and status', async () => {
    renderPage()

    const table = await screen.findByRole('table', { name: 'Picking tasks' })
    await within(table).findByText('Sam Staff')
    const rows = within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('SO-2026-000004urgent1WH01-ZA-R09-S01-B01AUT-FIL1')
    expect(rows[2]).toHaveTextContent('Sam Staff')
    expect(api.listPickingTasks).toHaveBeenLastCalledWith({
      status: 'open',
      mine: false,
      offset: 0,
      limit: 50,
    })
  })

  it('start opens the scan dialog; scans are checked as you type', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Start stop 1 of SO-2026-000004' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Pick 4 × AUT-FIL1' }))
    expect(dialog.getByText('WH01-ZA-R09-S01-B01')).toBeInTheDocument()

    await user.type(dialog.getByRole('textbox', { name: 'Scan the bin' }), 'WH01-ZA-R01-S01-B01')
    expect(dialog.getByText(/does not match this task/)).toBeInTheDocument()
    await user.clear(dialog.getByRole('textbox', { name: 'Scan the bin' }))
    await user.type(dialog.getByRole('textbox', { name: 'Scan the bin' }), 'wh01-za-r09-s01-b01')
    await user.type(dialog.getByRole('textbox', { name: /Scan the product/ }), '4000000000017')
    expect(dialog.getAllByText('matches')).toHaveLength(2)
    await user.click(dialog.getByRole('button', { name: 'Confirm pick' }))

    await waitFor(() =>
      expect(api.completePicking).toHaveBeenCalledWith(1, {
        bin_code: 'wh01-za-r09-s01-b01',
        product_code: '4000000000017',
        quantity_picked: 4,
        short_reason: undefined,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Picked 4 × AUT-FIL1')
  })

  it('a short pick needs a reason', async () => {
    const user = renderPage()

    await user.click(
      await screen.findByRole('button', { name: 'Confirm stop 2 of SO-2026-000004' }),
    )
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByRole('textbox', { name: 'Scan the bin' }), 'WH01-ZA-R09-S01-B01')
    await user.type(dialog.getByRole('textbox', { name: /Scan the product/ }), 'AUT-FIL1')
    const quantity = dialog.getByRole('textbox', { name: /Quantity picked/ })
    await user.clear(quantity)
    await user.type(quantity, '3')
    await user.click(dialog.getByRole('button', { name: 'Confirm pick' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Say why units are missing')

    await user.type(dialog.getByRole('textbox', { name: /Why are units missing/ }), 'Only 3 there')
    await user.click(dialog.getByRole('button', { name: 'Confirm pick' }))
    await waitFor(() =>
      expect(api.completePicking).toHaveBeenCalledWith(
        2,
        expect.objectContaining({ quantity_picked: 3, short_reason: 'Only 3 there' }),
      ),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('a cycle count was opened')
  })

  it('"only my tasks" is kept in the URL', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('checkbox', { name: 'Only tasks I started' }))
    expect(screen.getByTestId('location').textContent).toBe('/fulfillment?mine=1')
    await waitFor(() =>
      expect(api.listPickingTasks).toHaveBeenLastCalledWith(
        expect.objectContaining({ mine: true }),
      ),
    )
  })
})

describe('FulfillmentPage – packing and shipping', () => {
  it('the packer counts every line, then ships straight away', async () => {
    const user = renderPage('/fulfillment?view=packing')

    await user.click(await screen.findByRole('button', { name: 'Start packing SO-2026-000004' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Pack order SO-2026-000004' }))
    expect(dialog.getByText('1 short of the order')).toBeInTheDocument()

    await user.click(dialog.getByRole('button', { name: 'Packed' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Count AUT-FIL1')
    await user.type(dialog.getByRole('textbox', { name: 'Counted AUT-FIL1' }), '4')
    await user.type(dialog.getByRole('textbox', { name: 'Counted AUT-WIP1' }), '2')
    expect(dialog.getByRole('textbox', { name: 'Counted AUT-WIP1' })).toHaveClass('border-red-400')
    await user.clear(dialog.getByRole('textbox', { name: 'Counted AUT-WIP1' }))
    await user.type(dialog.getByRole('textbox', { name: 'Counted AUT-WIP1' }), '1')
    await user.clear(dialog.getByRole('textbox', { name: 'Parcels' }))
    await user.type(dialog.getByRole('textbox', { name: 'Parcels' }), '2')
    await user.type(dialog.getByRole('textbox', { name: /Total weight/ }), '3,5')
    await user.click(dialog.getByRole('button', { name: 'Packed' }))

    await waitFor(() =>
      expect(api.completePacking).toHaveBeenCalledWith(9, {
        items: [
          { product_id: 7, quantity: 4 },
          { product_id: 8, quantity: 1 },
        ],
        package_count: 2,
        weight_kg: '3.5',
      }),
    )
    const ship = within(await screen.findByRole('dialog', { name: 'Ship order SO-2026-000004' }))
    await user.click(ship.getByRole('button', { name: 'Ship' }))
    expect(ship.getByRole('alert')).toHaveTextContent('Choose a carrier')
    await waitFor(() =>
      expect(ship.getByRole('option', { name: 'DHL Paket (2 working days)' })).toBeInTheDocument(),
    )
    await user.selectOptions(ship.getByRole('combobox', { name: /Carrier/ }), '1')
    await user.click(ship.getByRole('button', { name: 'Ship' }))
    await waitFor(() =>
      expect(api.createShipment).toHaveBeenCalledWith({
        order_id: 4,
        carrier_id: 1,
        tracking_number: undefined,
        expected_delivery_date: undefined,
      }),
    )
    expect(await screen.findByText('Shipped with DHL DHL261106000001')).toBeInTheDocument()
  })

  it('packed orders wait under "Ready to ship"', async () => {
    const user = renderPage('/fulfillment?view=packing')

    const ready = await screen.findByRole('table', { name: 'Packed orders' })
    expect(await within(ready).findByText('SO-2026-000005')).toBeInTheDocument()
    expect(within(ready).getByText('1 · 2.000 kg')).toBeInTheDocument()
    await user.click(within(ready).getByRole('button', { name: 'Ship SO-2026-000005' }))
    expect(screen.getByRole('dialog', { name: 'Ship order SO-2026-000005' })).toBeInTheDocument()
  })
})

describe('/fulfillment route', () => {
  it('is not available to customers', async () => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs('customer')}>
          <MemoryRouter initialEntries={['/fulfillment']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listPickingTasks).not.toHaveBeenCalled()
  })
})
