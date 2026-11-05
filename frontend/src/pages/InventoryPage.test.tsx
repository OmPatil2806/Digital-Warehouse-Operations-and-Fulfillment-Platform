import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../api/healthApi'
import * as inventoryApi from '../api/inventoryApi'
import * as warehouseApi from '../api/warehouseApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { page } from '../test/catalogFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { makeMovement, makeProductStock, makeRow } from '../test/inventoryFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import InventoryPage from './InventoryPage'

vi.mock('../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/inventoryApi')>()),
  listInventory: vi.fn(),
  getProductStock: vi.fn(),
  listMovements: vi.fn(),
}))
vi.mock('../api/warehouseApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/warehouseApi')>()),
  listWarehouses: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(inventoryApi)

const MOVEMENTS = [
  makeMovement({
    id: 3,
    movement_type: 'transfer_out',
    quantity: 4,
    on_hand_delta: -4,
    on_hand_after: 6,
    reference_type: 'transfer',
    reference_id: 12,
    reason: 'Replenish picking',
  }),
  makeMovement({
    id: 2,
    movement_type: 'write_off',
    quantity: 2,
    on_hand_delta: -2,
    damaged_delta: -2,
    on_hand_after: 8,
    damaged_after: 0,
    reference_type: 'adjustment',
    reference_id: 5,
    reason: 'Broken',
  }),
  makeMovement({ id: 1, created_by: null }),
]

beforeEach(() => {
  vi.clearAllMocks()
  api.listInventory.mockResolvedValue(
    page([
      makeRow(),
      makeRow({
        id: 2,
        product: { id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' },
        bin: { id: 21, location_code: 'WH01-ZA-R01-S01-B02' },
        quantity_on_hand: 3,
        quantity_reserved: 3,
        quantity_damaged: 0,
        quantity_available: 0,
      }),
    ]),
  )
  api.getProductStock.mockResolvedValue(makeProductStock())
  api.listMovements.mockResolvedValue(page(MOVEMENTS))
  vi.mocked(warehouseApi.listWarehouses).mockResolvedValue([
    {
      id: 1,
      code: 'WH01',
      name: 'Main Distribution Centre',
      address: null,
      is_active: true,
      created_at: '',
      updated_at: '',
    },
  ])
})

function renderPage(path = '/inventory') {
  renderWithAuth(<InventoryPage />, { auth: loggedInAs('staff'), path, route: '/inventory' })
  return userEvent.setup()
}

const location = () => screen.getByTestId('location').textContent
const row = (text: string) => screen.getByText(text).closest('tr') as HTMLElement

describe('InventoryPage – stock', () => {
  it('lists stock per bin with on hand, reserved, damaged and available', async () => {
    renderPage()

    await screen.findByText('Wireless Mouse')
    const laptop = within(row('WH01-ZA-R01-S01-B01'))
    expect(laptop.getByText('LAP-1401')).toBeInTheDocument()
    expect(laptop.getAllByRole('cell').map((c) => c.textContent)).toEqual([
      'WH01-ZA-R01-S01-B01',
      'LAP-1401Laptop 14" Business',
      '10',
      '2',
      '1',
      '7',
    ])
    const mouse = within(row('Wireless Mouse'))
    expect(mouse.getAllByRole('cell')[4]).toHaveTextContent('—') // nothing damaged
    expect(mouse.getAllByRole('cell')[5].firstChild).toHaveClass('text-red-700') // 0 available
  })

  it('searches and filters by warehouse through the URL', async () => {
    const user = renderPage('/inventory?q=lap&warehouse=1')

    await screen.findByText('Wireless Mouse')
    expect(api.listInventory).toHaveBeenLastCalledWith({
      q: 'lap',
      warehouseId: 1,
      offset: 0,
      limit: 25,
    })

    await user.selectOptions(screen.getByRole('combobox', { name: 'Warehouse' }), 'All warehouses')
    expect(location()).toBe('/inventory?q=lap')
  })

  it('clicking a row shows where the product is stored', async () => {
    const user = renderPage()

    await user.click(await screen.findByText('Laptop 14" Business'))

    const dialog = within(
      await screen.findByRole('dialog', { name: 'LAP-1401 · Laptop 14" Business' }),
    )
    expect(api.getProductStock).toHaveBeenCalledWith(7)
    const bins = dialog.getByRole('table', { name: 'Bins holding this product' })
    await within(bins).findByText('WH01-ZB-R01-S01-B01')
    expect(dialog.getByText('11')).toBeInTheDocument() // available over all bins
    expect(dialog.getByRole('link', { name: /Movement history/ })).toHaveAttribute(
      'href',
      '/inventory?view=movements&product=7',
    )
    expect(location()).toBe('/inventory?product=7')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(location()).toBe('/inventory')
  })

  it('marks low and out-of-stock products', async () => {
    api.getProductStock.mockResolvedValue(
      makeProductStock({ is_low_stock: true, quantity_available: 0 }),
    )
    renderPage('/inventory?product=7')

    expect(await screen.findByText(/Out of stock · minimum 5/)).toBeInTheDocument()
  })
})

describe('InventoryPage – movement history', () => {
  it('shows each movement with its change, balance and reference', async () => {
    renderPage('/inventory?view=movements')

    const history = await screen.findByRole('table', { name: 'Movement history' })
    await within(history).findByText('Transfer #12')
    const transfer = within(row('Transfer #12'))
    expect(transfer.getByText('Moved out')).toBeInTheDocument()
    expect(transfer.getByText('−4 on hand')).toBeInTheDocument()
    expect(transfer.getByText('6 on hand')).toBeInTheDocument()
    expect(transfer.getByText('Replenish picking')).toBeInTheDocument()
    expect(transfer.getByText('Sam Staff')).toBeInTheDocument()

    const writeOff = within(row('Adjustment #5'))
    expect(writeOff.getByText('Written off')).toBeInTheDocument()
    expect(writeOff.getByText('−2 on hand, −2 damaged')).toBeInTheDocument()

    const receipt = within(row('PO-1001'))
    expect(receipt.getByText('+10 on hand')).toBeInTheDocument()
    expect(receipt.getByText('System')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Movement history' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('filters by movement type and product, and the product filter can be cleared', async () => {
    const user = renderPage('/inventory?view=movements&product=7')

    await screen.findByText('Transfer #12')
    expect(api.listMovements).toHaveBeenLastCalledWith({
      productId: 7,
      binId: undefined,
      movementType: undefined,
      offset: 0,
      limit: 25,
    })
    expect(await screen.findByText('LAP-1401 · Laptop 14" Business')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument() // no dialog in this view

    await user.selectOptions(screen.getByRole('combobox', { name: 'Movement type' }), 'Received')
    expect(location()).toBe('/inventory?view=movements&product=7&type=receipt')
    await waitFor(() =>
      expect(api.listMovements).toHaveBeenLastCalledWith(
        expect.objectContaining({ movementType: 'receipt' }),
      ),
    )

    await user.click(screen.getByRole('button', { name: 'Show all products' }))
    expect(location()).toBe('/inventory?view=movements&type=receipt')
  })

  it('switching tabs resets the view-specific filters', async () => {
    const user = renderPage('/inventory?view=movements&type=damage')

    await user.click(await screen.findByRole('tab', { name: 'Stock' }))

    expect(location()).toBe('/inventory')
    await screen.findByText('Wireless Mouse')
  })
})

describe('/inventory route', () => {
  it('is not available to customers', async () => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs('customer')}>
          <MemoryRouter initialEntries={['/inventory']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )

    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listInventory).not.toHaveBeenCalled()
  })
})
