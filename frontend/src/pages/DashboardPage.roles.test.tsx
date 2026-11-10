import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as alertsApi from '../api/alertsApi'
import * as dashboardApi from '../api/dashboardApi'
import * as fulfillmentApi from '../api/fulfillmentApi'
import * as healthApi from '../api/healthApi'
import * as ordersApi from '../api/ordersApi'
import { page } from '../test/catalogFixtures'
import { makeFulfillment, makeInventory, makeOverview } from '../test/dashboardFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { makeOrderSummary, makeShipment } from '../test/orderFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { Alert } from '../types/alerts'
import DashboardPage from './DashboardPage'

vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
vi.mock('../api/dashboardApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/dashboardApi')>()),
  getOverviewDashboard: vi.fn(),
  getFulfillmentDashboard: vi.fn(),
  getInventoryDashboard: vi.fn(),
}))
vi.mock('../api/alertsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/alertsApi')>()),
  listAlerts: vi.fn(),
}))
vi.mock('../api/fulfillmentApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/fulfillmentApi')>()),
  listPickingTasks: vi.fn(),
  listPackingTasks: vi.fn(),
  listShipments: vi.fn(),
}))
vi.mock('../api/ordersApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/ordersApi')>()),
  listOrders: vi.fn(),
}))
const dashboards = vi.mocked(dashboardApi)

const ALERT: Alert = {
  id: 1,
  created_at: '2026-11-10T08:00:00Z',
  updated_at: '2026-11-10T08:00:00Z',
  alert_type: 'overdue_supplier',
  severity: 'critical',
  status: 'open',
  title: 'Overdue delivery: PO-2026-000001',
  message: 'AutoParts Europa SpA is 8 day(s) late',
  product: null,
  bin: null,
  acknowledged_by: null,
  acknowledged_at: null,
  resolved_by: null,
  resolved_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(healthApi.getHealth).mockResolvedValue(makeHealthResponse())
  dashboards.getOverviewDashboard.mockResolvedValue(makeOverview())
  dashboards.getFulfillmentDashboard.mockResolvedValue(makeFulfillment())
  dashboards.getInventoryDashboard.mockResolvedValue(makeInventory())
  vi.mocked(alertsApi.listAlerts).mockResolvedValue(page([ALERT], 8))
  vi.mocked(fulfillmentApi.listPickingTasks).mockResolvedValue(page([], 12))
  vi.mocked(fulfillmentApi.listPackingTasks).mockResolvedValue(page([], 3))
  vi.mocked(fulfillmentApi.listShipments).mockResolvedValue(page([makeShipment()]))
  vi.mocked(ordersApi.listOrders).mockResolvedValue(page([makeOrderSummary({ status: 'shipped' })]))
})

function renderPage(role: Role, path = '/') {
  renderWithAuth(<DashboardPage />, { auth: loggedInAs(role), path, route: '/' })
  return userEvent.setup()
}

async function tile(name: string) {
  return within(await screen.findByRole('region', { name }))
}

describe('DashboardPage for managers', () => {
  it('shows the headline KPIs of the period', async () => {
    renderPage('manager')

    await waitFor(async () =>
      expect((await tile('Stock value')).getByText('€70,552.10')).toBeInTheDocument(),
    )
    expect((await tile('Stock value')).getByText(/4,026 units available/)).toBeInTheDocument()
    expect((await tile('Open orders')).getByText('1 waiting for stock')).toBeInTheDocument()
    expect(
      (await tile('Orders shipped')).getByText('in the last 30 days · 2 today'),
    ).toBeInTheDocument()
    expect((await tile('On-time delivery')).getByText('75 %')).toBeInTheDocument()
    expect((await tile('On-time delivery')).getByText(/3 of 4 deliveries/)).toBeInTheDocument()
    expect((await tile('Open alerts')).getByText('1 critical')).toBeInTheDocument()
    expect((await tile('Purchase orders')).getByText('1 overdue')).toBeInTheDocument()
    expect(
      (await tile('Purchase orders')).getByText(/€1,812.00 still to arrive/),
    ).toBeInTheDocument()
    expect(dashboards.getInventoryDashboard).toHaveBeenCalledWith(expect.anything(), 5)
  })

  it('shows the charts with a table view, the urgent products and the latest alerts', async () => {
    const user = renderPage('manager')

    const trend = await screen.findByRole('figure', { name: 'Orders per day' })
    await user.click(await within(trend).findByRole('button', { name: 'Show table' }))
    const rows = within(within(trend).getByRole('table')).getAllByRole('row')
    expect(rows.map((r) => r.textContent)).toEqual([
      'DayPlacedShippedDelivered',
      '8 Nov210',
      '9 Nov000',
      '10 Nov521',
    ])

    const stock = screen.getByRole('figure', { name: 'Stock status' })
    expect(
      await within(stock).findByText('50 active products by what is available now'),
    ).toBeInTheDocument()
    await user.click(await within(stock).findByRole('button', { name: 'Show table' }))
    expect(within(stock).getByRole('row', { name: 'Below minimum 5' })).toBeInTheDocument()

    const urgent = within(screen.getByRole('table', { name: /fewest days of supply/ }))
    expect(
      urgent.getByRole('row', { name: /TOO-LAD1 .* Out of stock 0 0 days/ }),
    ).toBeInTheDocument()
    expect(
      urgent.getByRole('row', { name: /ACC-HDS1.*Below minimum 6 no demand/ }),
    ).toBeInTheDocument()
    expect(
      urgent.getByRole('row', { name: /HOM-KET1 Electric Kettle 37 370 days/ }),
    ).toBeInTheDocument()

    const alerts = within(screen.getByRole('region', { name: 'Latest alerts' }))
    expect(alerts.getByText('Overdue delivery: PO-2026-000001')).toBeInTheDocument()
    expect(alerts.getByLabelText('Critical')).toBeInTheDocument()
    expect(alerts.getByRole('link', { name: 'All 8 open alerts' })).toHaveAttribute(
      'href',
      '/alerts',
    )
    expect(screen.getByRole('region', { name: 'ML insights' })).toHaveTextContent('Phases 8')
  })

  it('reloads every dashboard for a new period', async () => {
    const user = renderPage('manager')
    await screen.findByRole('figure', { name: 'Orders per day' })

    await user.click(screen.getByRole('button', { name: 'Last 7 days' }))
    await waitFor(() => {
      const range = dashboards.getOverviewDashboard.mock.lastCall?.[0]
      expect(range?.date_from && range.date_to).toBeTruthy()
      const days = (Date.parse(range!.date_to!) - Date.parse(range!.date_from!)) / 86_400_000 + 1
      expect(days).toBe(7)
    })
    expect(dashboards.getFulfillmentDashboard.mock.lastCall?.[0]).toEqual(
      dashboards.getOverviewDashboard.mock.lastCall?.[0],
    )
  })

  it('uses a custom range from the address bar', async () => {
    renderPage('manager', '/?range=custom&from=2026-10-01&to=2026-10-31')
    await screen.findByRole('figure', { name: 'Orders per day' })

    expect(dashboards.getOverviewDashboard).toHaveBeenCalledWith({
      date_from: '2026-10-01',
      date_to: '2026-10-31',
    })
    expect(screen.getByRole('button', { name: 'Custom range' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('explains an empty period and a failed request', async () => {
    dashboards.getFulfillmentDashboard.mockResolvedValue(
      makeFulfillment({
        per_day: [{ day: '2026-11-10', placed: 0, shipped: 0, delivered: 0 }],
        on_time_delivery: { good: 0, total: 0, percent: null },
      }),
    )
    dashboards.getInventoryDashboard.mockRejectedValue(new Error('boom'))
    renderPage('manager')

    expect(
      await screen.findByText(/No orders were placed, shipped or delivered/),
    ).toBeInTheDocument()
    expect((await tile('On-time delivery')).getByText('—')).toBeInTheDocument()
    expect((await tile('On-time delivery')).getByText(/No deliveries/)).toBeInTheDocument()
    const stock = screen.getByRole('figure', { name: 'Stock status' })
    await waitFor(() => expect(within(stock).getByRole('alert')).toBeInTheDocument())
  })
})

describe('DashboardPage for staff', () => {
  it("shows today's work and no money", async () => {
    renderPage('staff')

    await waitFor(async () => expect((await tile('To pick')).getByText('12')).toBeInTheDocument())
    expect((await tile('To pack')).getByText('3')).toBeInTheDocument()
    expect((await tile('To pack')).getByRole('link', { name: 'Packing station' })).toHaveAttribute(
      'href',
      '/fulfillment?view=packing',
    )
    expect((await tile('Shipped today')).getByText('2 parcels on the way')).toBeInTheDocument()
    expect((await tile('Delayed shipments')).getByText('Needs follow-up')).toBeInTheDocument()
    expect((await tile('Low stock')).getByText('6')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Latest alerts' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Stock value' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Last 7 days' })).not.toBeInTheDocument()
    expect(dashboards.getFulfillmentDashboard).not.toHaveBeenCalled()
    expect(screen.queryByText(/€/)).not.toBeInTheDocument()
  })
})

describe('DashboardPage for customers', () => {
  it('shows their own recent orders and parcels, no warehouse KPIs', async () => {
    renderPage('customer')

    const orders = within(await screen.findByRole('region', { name: 'My recent orders' }))
    expect(await orders.findByRole('link', { name: 'SO-2026-000001' })).toHaveAttribute(
      'href',
      '/orders/1',
    )
    expect(orders.getByText('Shipped')).toBeInTheDocument()
    const parcels = within(screen.getByRole('region', { name: 'My parcels' }))
    expect(await parcels.findByText(/DHL261106000001/)).toBeInTheDocument()
    expect(parcels.getByText(/expected 10 Nov 2026/)).toBeInTheDocument()

    expect(dashboards.getOverviewDashboard).not.toHaveBeenCalled()
    expect(alertsApi.listAlerts).not.toHaveBeenCalled()
    expect(screen.queryByRole('region', { name: 'Latest alerts' })).not.toBeInTheDocument()
  })

  it('invites a first order', async () => {
    vi.mocked(ordersApi.listOrders).mockResolvedValue(page([]))
    vi.mocked(fulfillmentApi.listShipments).mockResolvedValue(page([]))
    renderPage('customer')

    expect(await screen.findByText('You have not placed an order yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /All orders and new order/ })).toHaveAttribute(
      'href',
      '/orders',
    )
    expect(await screen.findByText('No parcels yet.')).toBeInTheDocument()
  })
})
