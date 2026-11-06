import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import * as purchasingApi from '../api/purchasingApi'
import * as warehouseApi from '../api/warehouseApi'
import { makeProduct, makeSupplier, page } from '../test/catalogFixtures'
import { makeBinDetail } from '../test/opsMocks'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import type { PurchaseOrder } from '../types/purchasing'
import PurchaseOrdersPage from './PurchaseOrdersPage'

vi.mock('../api/purchasingApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/purchasingApi')>()),
  listPurchaseOrders: vi.fn(),
  createPurchaseOrder: vi.fn(),
  purchaseOrderAction: vi.fn(),
  receivePurchaseOrder: vi.fn(),
  checkOverduePurchaseOrders: vi.fn(),
}))
vi.mock('../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/catalogApi')>()),
  listSuppliers: vi.fn(),
  listProducts: vi.fn(),
}))
vi.mock('../api/warehouseApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/warehouseApi')>()),
  listWarehouses: vi.fn(),
  getBinByCode: vi.fn(),
}))
const api = vi.mocked(purchasingApi)

function makePo(overrides: Partial<PurchaseOrder> = {}): PurchaseOrder {
  return {
    id: 1,
    po_number: 'PO-2026-000001',
    supplier: { id: 4, code: 'SUP-004', name: 'AutoParts Europa SpA' },
    warehouse: { id: 1, code: 'WH01', name: 'Main' },
    status: 'ordered',
    expected_date: '2026-11-02',
    is_overdue: true,
    notes: 'Demo purchase order',
    total_cost: '1440.00',
    created_by: { id: 2, full_name: 'Mia Manager', email: 'manager@example.com' },
    created_at: '2026-11-01T09:00:00Z',
    ordered_at: '2026-11-01T09:05:00Z',
    received_at: null,
    items: [
      {
        id: 1,
        product: { id: 20, sku: 'AUT-BAT1', name: 'Car Battery 12 V 70 Ah' },
        quantity: 20,
        unit_cost: '72.00',
        quantity_received: 0,
        quantity_outstanding: 20,
      },
    ],
    ...overrides,
  }
}

const DRAFT = makePo({
  id: 2,
  po_number: 'PO-2026-000002',
  status: 'draft',
  is_overdue: false,
  ordered_at: null,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listPurchaseOrders.mockResolvedValue(page([makePo(), DRAFT]))
  api.checkOverduePurchaseOrders.mockResolvedValue([makePo()])
  api.purchaseOrderAction.mockImplementation(async (_id, action) =>
    action === 'order'
      ? { ...DRAFT, status: 'ordered', ordered_at: '2026-11-06T10:00:00Z' }
      : { ...DRAFT, status: 'cancelled' },
  )
  api.receivePurchaseOrder.mockResolvedValue(
    makePo({
      status: 'partially_received',
      items: [{ ...makePo().items[0], quantity_received: 12, quantity_outstanding: 8 }],
    }),
  )
  api.createPurchaseOrder.mockResolvedValue(DRAFT)
  vi.mocked(catalogApi.listSuppliers).mockResolvedValue(
    page([makeSupplier({ id: 4, code: 'SUP-004', name: 'AutoParts Europa SpA' })]),
  )
  vi.mocked(catalogApi.listProducts).mockResolvedValue(
    page([makeProduct({ id: 20, sku: 'AUT-BAT1', name: 'Car Battery 12 V 70 Ah' })]),
  )
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
  vi.mocked(warehouseApi.getBinByCode).mockImplementation(async (code) =>
    makeBinDetail(code, code.startsWith('WH02') ? 99 : 31),
  )
})

function renderPage(role: Role = 'manager') {
  renderWithAuth(<PurchaseOrdersPage />, {
    auth: loggedInAs(role),
    path: '/purchase-orders',
    route: '/purchase-orders',
  })
  return userEvent.setup()
}

describe('PurchaseOrdersPage', () => {
  it('lists purchase orders with overdue marks; managers check overdue', async () => {
    const user = renderPage()

    const row = (await screen.findByText('PO-2026-000001')).closest('tr')!
    expect(within(row).getByText('overdue')).toBeInTheDocument()
    expect(within(row).getByText('0/20 × AUT-BAT1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Check overdue' }))
    expect(await screen.findByText('1 purchase order(s) overdue — see Alerts')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Only overdue' }))
    await waitFor(() =>
      expect(api.listPurchaseOrders).toHaveBeenLastCalledWith(
        expect.objectContaining({ overdue: true }),
      ),
    )
  })

  it('staff can receive but not create, order or cancel', async () => {
    const user = renderPage('staff')

    await user.click(await screen.findByText('PO-2026-000002'))
    let dialog = within(screen.getByRole('dialog'))
    expect(dialog.queryByRole('button', { name: 'Send to supplier' })).not.toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: 'Cancel order' })).not.toBeInTheDocument()
    expect(dialog.queryByRole('button', { name: 'Receive goods' })).not.toBeInTheDocument()
    await user.click(dialog.getByRole('button', { name: 'Close' }))

    expect(screen.queryByRole('button', { name: 'New purchase order' })).not.toBeInTheDocument()
    await user.click(screen.getByText('PO-2026-000001'))
    dialog = within(screen.getByRole('dialog'))
    expect(dialog.getByRole('button', { name: 'Receive goods' })).toBeInTheDocument()
  })

  it('receives part of an order into a bin of the right warehouse', async () => {
    const user = renderPage('staff')

    await user.click(await screen.findByText('PO-2026-000001'))
    await user.click(screen.getByRole('button', { name: 'Receive goods' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Receive PO-2026-000001' }))
    const quantity = dialog.getByLabelText('Received AUT-BAT1')
    expect(quantity).toHaveValue('20')

    await user.click(dialog.getByRole('button', { name: 'Book into stock' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('AUT-BAT1: choose the bin it goes into')

    const bin = dialog.getByLabelText(/Bin for AUT-BAT1/)
    await user.type(bin, 'WH02-ZA-R01-S01-B01{Enter}')
    await user.click(dialog.getByRole('button', { name: 'Book into stock' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('the bin must be in WH01')
    expect(api.receivePurchaseOrder).not.toHaveBeenCalled()

    await user.clear(bin)
    await user.type(bin, 'WH01-ZA-R01-S01-B02{Enter}')
    await user.clear(quantity)
    await user.type(quantity, '25')
    await user.click(dialog.getByRole('button', { name: 'Book into stock' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('only 20 outstanding')

    await user.clear(quantity)
    await user.type(quantity, '12')
    await user.click(dialog.getByRole('button', { name: 'Book into stock' }))
    await waitFor(() =>
      expect(api.receivePurchaseOrder).toHaveBeenCalledWith(1, [
        { product_id: 20, quantity: 12, bin_id: 31 },
      ]),
    )
    expect(
      await screen.findByText('PO-2026-000001 partly received — stock updated'),
    ).toBeInTheDocument()
    const detail = within(screen.getByRole('dialog', { name: 'Purchase order PO-2026-000001' }))
    expect(detail.getByText('Partially received')).toBeInTheDocument()
  })

  it('managers send a draft to the supplier', async () => {
    const user = renderPage()

    await user.click(await screen.findByText('PO-2026-000002'))
    const dialog = within(screen.getByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Send to supplier' }))
    await waitFor(() => expect(api.purchaseOrderAction).toHaveBeenCalledWith(2, 'order'))
    expect(
      await screen.findByText('Purchase order PO-2026-000002 sent to AutoParts Europa SpA'),
    ).toBeInTheDocument()
    expect(dialog.getByRole('button', { name: 'Receive goods' })).toBeInTheDocument()
  })

  it('drafts a new purchase order', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'New purchase order' }))
    const dialog = within(screen.getByRole('dialog', { name: 'New purchase order' }))
    await user.click(dialog.getByRole('button', { name: 'Save draft' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('Choose a supplier')

    await user.selectOptions(
      await dialog.findByRole('combobox', { name: /Supplier/ }),
      await dialog.findByRole('option', { name: /SUP-004/ }),
    )
    await user.type(dialog.getByPlaceholderText('Type a SKU or name'), 'battery')
    await user.click(await dialog.findByRole('button', { name: /AUT-BAT1/ }))
    const quantity = dialog.getByLabelText('Quantity of AUT-BAT1')
    await user.clear(quantity)
    await user.type(quantity, '20')
    await user.type(dialog.getByLabelText('Unit cost of AUT-BAT1'), '7,5')
    await user.click(dialog.getByRole('button', { name: 'Save draft' }))
    expect(dialog.getByRole('alert')).toHaveTextContent('enter a price like 12.50')

    await user.clear(dialog.getByLabelText('Unit cost of AUT-BAT1'))
    await user.click(dialog.getByRole('button', { name: 'Save draft' }))
    await waitFor(() =>
      expect(api.createPurchaseOrder).toHaveBeenCalledWith(
        {
          supplier_id: 4,
          warehouse_id: 1,
          expected_date: undefined,
          notes: undefined,
          items: [{ product_id: 20, quantity: 20, unit_cost: undefined }],
        },
        expect.anything(),
      ),
    )
    expect(await screen.findByText('Purchase order PO-2026-000002 drafted')).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Purchase order PO-2026-000002' })).toBeVisible()
  })
})
