import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as dashboardApi from '../api/dashboardApi'
import * as csv from '../utils/csv'
import {
  makeFulfillment,
  makeInventory,
  makeSuppliers,
  makeWarehouse,
} from '../test/dashboardFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import ReportsPage from './ReportsPage'

vi.mock('../api/dashboardApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/dashboardApi')>()),
  getInventoryDashboard: vi.fn(),
  getFulfillmentDashboard: vi.fn(),
  getWarehouseDashboard: vi.fn(),
  getSupplierDashboard: vi.fn(),
}))
vi.mock('../utils/csv', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../utils/csv')>()),
  downloadCsv: vi.fn(),
}))
const api = vi.mocked(dashboardApi)
const download = vi.mocked(csv.downloadCsv)

/** The file the last export produced: name and CSV text. */
function lastExport() {
  const [name, table] = download.mock.lastCall!
  return { name, text: csv.toCsv(table), rows: table.rows.length }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getInventoryDashboard.mockResolvedValue(makeInventory())
  api.getFulfillmentDashboard.mockResolvedValue(makeFulfillment())
  api.getWarehouseDashboard.mockResolvedValue(makeWarehouse())
  api.getSupplierDashboard.mockResolvedValue(makeSuppliers())
})

function renderPage(role: Role = 'manager', path = '/reports') {
  renderWithAuth(<ReportsPage />, { auth: loggedInAs(role), path, route: '/reports' })
  return userEvent.setup()
}

async function tile(name: string) {
  const region = await screen.findByRole('region', { name })
  await waitFor(() => expect(region).toHaveAttribute('aria-busy', 'false'))
  return within(region)
}

async function chartTable(user: ReturnType<typeof userEvent.setup>, title: string) {
  const figure = await screen.findByRole('figure', { name: title })
  await user.click(await within(figure).findByRole('button', { name: 'Show table' }))
  return within(figure)
    .getAllByRole('row')
    .map((r) => r.textContent)
}

describe('ReportsPage', () => {
  it('shows the inventory report with money for managers', async () => {
    const user = renderPage()

    expect(screen.getByRole('tab', { name: 'Inventory' })).toHaveAttribute('aria-selected', 'true')
    expect((await tile('Stock value')).getByText('€70,552.10')).toBeInTheDocument()
    expect(
      (await tile('Stock value')).getByText('€128,380.79 at selling price'),
    ).toBeInTheDocument()
    expect((await tile('Turnover')).getByText('0.01×')).toBeInTheDocument()
    expect((await tile('Days of supply')).getByText('1,520.5 days')).toBeInTheDocument()
    expect(await chartTable(user, 'Stock value per category')).toEqual([
      'CategoryProductsUnitsValue at costValue at price',
      'Laptops420€28,960.00€38,000.00',
      'Tools690€2,790.00€5,310.00',
    ])
    const products = within(screen.getByRole('table', { name: 'Product stock KPIs' }))
    expect(products.getByRole('columnheader', { name: 'Value' })).toBeInTheDocument()
    expect(
      products.getByRole('row', { name: /TOO-LAD1.*Out of stock 0 3 1 0.03 0 days —/ }),
    ).toBeInTheDocument()
    expect(screen.getByText('(first 3 of 50)')).toBeInTheDocument()
    expect(api.getInventoryDashboard).toHaveBeenCalledWith(expect.anything(), 25)
  })

  it('hides money from staff', async () => {
    const user = renderPage('staff')

    expect((await tile('Units on hand')).getByText('4,036')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Stock value' })).not.toBeInTheDocument()
    expect(await chartTable(user, 'Units per category')).toEqual([
      'CategoryProductsUnits',
      'Laptops420',
      'Tools690',
    ])
    const products = within(screen.getByRole('table', { name: 'Product stock KPIs' }))
    expect(products.queryByRole('columnheader', { name: 'Value' })).not.toBeInTheDocument()
    expect(screen.queryByText(/€/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Suppliers' }))
    await tile('Average lead time')
    expect(screen.queryByRole('region', { name: 'Still to arrive' })).not.toBeInTheDocument()
    const suppliers = within(screen.getByRole('table', { name: 'Suppliers' }))
    expect(suppliers.queryByRole('columnheader', { name: 'To arrive' })).not.toBeInTheDocument()
  })

  it('shows fulfillment speed, quality and orders by status', async () => {
    const user = renderPage('manager', '/reports?view=fulfillment')

    expect((await tile('Fulfillment time')).getByText('22 h')).toBeInTheDocument()
    expect((await tile('Fulfillment time')).getByText(/median 12 h · 3 orders/)).toBeInTheDocument()
    expect((await tile('Order cycle time')).getByText('4.1 days')).toBeInTheDocument()
    expect((await tile('Order cycle time')).getByText(/1 order$/)).toBeInTheDocument()
    expect(
      (await tile('On-time delivery')).getByText(/3 of 4 deliveries · picking accuracy 100 %/),
    ).toBeInTheDocument()
    expect(await chartTable(user, 'Orders by status')).toEqual([
      'StatusOrders',
      'Created1',
      'Shipped2', // statuses without orders are left out
    ])
    expect(await chartTable(user, 'Orders per day')).toHaveLength(4)
  })

  it('shows how full the zones are and where picks come from', async () => {
    const user = renderPage('staff', '/reports?view=warehouse')

    expect((await tile('Bins in use')).getByText('30.7 %')).toBeInTheDocument()
    expect((await tile('Bins in use')).getByText('84 of 274 active bins')).toBeInTheDocument()
    expect((await tile('Volume used')).getByText('5.338 of 38.4 m³')).toBeInTheDocument()
    expect((await tile('Picks')).getByText('4')).toBeInTheDocument()
    expect(await chartTable(user, 'Zone use')).toEqual([
      'ZoneBins in useWeight usedVolume used',
      'ZA · Picking26 %14.9 %13.9 %',
      'ZC · Cold storage62.5 %52.1 %13.9 %', // the zone without bins is not charted
    ])
    const zones = within(screen.getByRole('table', { name: 'Zones' }))
    expect(zones.getByRole('row', { name: /Empty zone bulk 0 \/ 0 — —/ })).toBeInTheDocument()
  })

  it('compares promised and actual supplier lead times', async () => {
    const user = renderPage('manager', '/reports?view=suppliers')

    expect((await tile('Average lead time')).getByText('7.8 days')).toBeInTheDocument()
    expect(
      (await tile('Average lead time')).getByText(/± 2.8 days \(std. dev.\)/),
    ).toBeInTheDocument()
    expect((await tile('Open purchase orders')).getByText('1 overdue')).toBeInTheDocument()
    expect((await tile('Still to arrive')).getByText('€1,812.00')).toBeInTheDocument()
    expect(await chartTable(user, 'Lead time: promised and actual')).toEqual([
      'SupplierPromised lead timeActual (average)Variation (std. dev.)',
      'SUP-001 · Nordtech Distribution GmbH5 days7.8 days2.8 days', // SUP-004 received nothing
    ])
    const suppliers = within(screen.getByRole('table', { name: 'Suppliers' }))
    expect(
      suppliers.getByRole('row', { name: /SUP-004.*9 days 0 — — — 1 1 overdue €1,440.00/ }),
    ).toBeInTheDocument()
  })

  it('keeps one period for every tab, in the address bar', async () => {
    const user = renderPage('manager', '/reports?range=custom&from=2026-10-01&to=2026-10-31')
    await tile('Stock value')
    expect(api.getInventoryDashboard).toHaveBeenLastCalledWith(
      { date_from: '2026-10-01', date_to: '2026-10-31' },
      25,
    )

    await user.click(screen.getByRole('tab', { name: 'Warehouse' }))
    await tile('Bins in use')
    expect(api.getWarehouseDashboard).toHaveBeenLastCalledWith({
      date_from: '2026-10-01',
      date_to: '2026-10-31',
    })

    await user.click(screen.getByRole('button', { name: 'Last 7 days' }))
    await waitFor(() => {
      const range = api.getWarehouseDashboard.mock.lastCall?.[0]
      expect(range?.date_from).not.toBe('2026-10-01')
      const days = (Date.parse(range!.date_to!) - Date.parse(range!.date_from!)) / 86_400_000 + 1
      expect(days).toBe(7)
    })
    expect(screen.getByRole('tab', { name: 'Warehouse' })).toHaveAttribute('aria-selected', 'true')
  })

  it('shows empty charts when nothing happened', async () => {
    api.getSupplierDashboard.mockResolvedValue(
      makeSuppliers({
        suppliers: [],
        received_orders: 0,
        on_time: { good: 0, total: 0, percent: null },
      }),
    )
    renderPage('manager', '/reports?view=suppliers')

    expect(
      await screen.findAllByText('No purchase order was fully received in this period.'),
    ).toHaveLength(2)
    expect(
      (await tile('Average lead time')).getByText(/No purchase order fully received/),
    ).toBeInTheDocument()
  })
})

describe('CSV export', () => {
  const custom = 'range=custom&from=2026-10-01&to=2026-10-31'

  it('exports every product, with money, for managers', async () => {
    api.getInventoryDashboard.mockImplementation(async (_range, limit) =>
      limit === 500 ? makeInventory() : makeInventory({ products: [] }),
    )
    const user = renderPage('manager', `/reports?${custom}`)
    await tile('Stock value')

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    await waitFor(() => expect(download).toHaveBeenCalledOnce())
    expect(api.getInventoryDashboard).toHaveBeenLastCalledWith(
      { date_from: '2026-10-01', date_to: '2026-10-31' },
      500,
    )
    const file = lastExport()
    expect(file.name).toBe('inventory-report_2026-10-01_2026-10-31.csv')
    expect(file.text.split('\r\n').slice(0, 2)).toEqual([
      'sku,name,category,status,min_stock,units_on_hand,units_available,units_picked,avg_daily_demand,days_of_supply,turnover,value_at_cost_eur',
      'TOO-LAD1,Aluminium Step Ladder,Tools,out,3,0,0,1,0.03,0.0,,0.00',
    ])
    expect(
      await screen.findByText(/Saved inventory-report_2026-10-01_2026-10-31.csv \(3 rows\)/),
    ).toBeInTheDocument()
  })

  it('leaves money out of staff exports', async () => {
    const user = renderPage('staff', '/reports?view=suppliers')
    await tile('Average lead time')

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    await waitFor(() => expect(download).toHaveBeenCalledOnce())
    const header = lastExport().text.split('\r\n')[0]
    expect(header).toContain('lead_time_stddev_days')
    expect(header).not.toContain('open_value')
    expect(lastExport().text).not.toContain('1440')
  })

  it.each([
    ['fulfillment', 'Orders placed', 'fulfillment-per-day', 'day,placed,shipped,delivered', 3],
    [
      'warehouse',
      'Bins in use',
      'warehouse-zones',
      'warehouse,zone,name,zone_type,is_active,bins',
      3,
    ],
  ])('exports the %s table', async (view, tileName, name, header, rows) => {
    const user = renderPage('manager', `/reports?view=${view}&${custom}`)
    await tile(tileName)

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    await waitFor(() => expect(download).toHaveBeenCalledOnce())
    const file = lastExport()
    expect(file.name).toBe(`${name}_2026-10-01_2026-10-31.csv`)
    expect(file.text.startsWith(header)).toBe(true)
    expect(file.rows).toBe(rows)
  })

  it('reports a failed export', async () => {
    const user = renderPage('manager')
    await tile('Stock value')
    api.getInventoryDashboard.mockRejectedValueOnce(new Error('Server down'))

    await user.click(screen.getByRole('button', { name: 'Export CSV' }))
    expect(await screen.findByText(/Export failed/)).toBeInTheDocument()
    expect(download).not.toHaveBeenCalled()
  })

  it('cannot export before the report has loaded', () => {
    api.getWarehouseDashboard.mockReturnValue(new Promise(() => {}))
    renderPage('manager', '/reports?view=warehouse')
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled()
  })
})
