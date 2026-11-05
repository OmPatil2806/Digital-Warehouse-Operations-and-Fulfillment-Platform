import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import { makeOffer, makeProduct, makeSupplier, page } from '../test/catalogFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import SupplierDetailPage from './SupplierDetailPage'
import SuppliersPage from './SuppliersPage'

vi.mock('../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/catalogApi')>()),
  listSuppliers: vi.fn(),
  createSupplier: vi.fn(),
  getSupplier: vi.fn(),
  getSupplierProducts: vi.fn(),
  addSupplierProduct: vi.fn(),
  removeSupplierProduct: vi.fn(),
  listProducts: vi.fn(),
}))
const api = vi.mocked(catalogApi)

const NORDTECH = makeSupplier()
const BALTIC = makeSupplier({
  id: 10,
  code: 'SUP-010',
  name: 'Baltic Wholesale UAB',
  reliability_score: '0.85',
  lead_time_days: 12,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listSuppliers.mockResolvedValue(page([NORDTECH, BALTIC]))
  api.getSupplier.mockResolvedValue(NORDTECH)
  api.getSupplierProducts.mockResolvedValue([makeOffer()])
  api.listProducts.mockResolvedValue(
    page([makeProduct(), makeProduct({ id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' })]),
  )
})

describe('SuppliersPage', () => {
  function renderList(role: Role = 'manager') {
    renderWithAuth(<SuppliersPage />, {
      auth: loggedInAs(role),
      path: '/suppliers',
      routes: { '/suppliers/:id': <p>detail</p> },
    })
    return userEvent.setup()
  }

  it('lists suppliers and highlights low reliability', async () => {
    renderList()

    await screen.findByText('SUP-001') // rows appear once loaded
    const table = screen.getByRole('table', { name: 'Suppliers' })
    expect(within(table).getByText('97 %')).not.toHaveClass('text-amber-700')
    expect(within(table).getByText('85 %')).toHaveClass('text-amber-700')
    expect(within(table).getByText('12 days')).toBeInTheDocument()
  })

  it('creates a supplier (reliability entered as a percentage)', async () => {
    api.createSupplier.mockResolvedValue(makeSupplier({ id: 20, code: 'SUP-020' }))
    const user = renderList()

    await user.click(await screen.findByRole('button', { name: 'New supplier' }))
    await user.type(screen.getByRole('textbox', { name: /Code/ }), 'SUP-020')
    await user.type(screen.getByRole('textbox', { name: /^Name/ }), 'Alpine Supply AG')
    await user.type(screen.getByRole('textbox', { name: 'Email' }), 'not-an-email')
    await user.click(screen.getByRole('button', { name: 'Create supplier' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()

    await user.clear(screen.getByRole('textbox', { name: 'Email' }))
    await user.clear(screen.getByRole('textbox', { name: /Reliability/ }))
    await user.type(screen.getByRole('textbox', { name: /Reliability/ }), '90')
    await user.click(screen.getByRole('button', { name: 'Create supplier' }))

    await waitFor(() => expect(api.createSupplier).toHaveBeenCalled())
    expect(api.createSupplier.mock.calls[0][0]).toMatchObject({
      code: 'SUP-020',
      name: 'Alpine Supply AG',
      email: null,
      lead_time_days: 7,
      reliability_score: '0.90',
    })
  })

  it('staff get no "New supplier" button', async () => {
    renderList('staff')

    await screen.findByText('SUP-001')
    expect(screen.queryByRole('button', { name: 'New supplier' })).not.toBeInTheDocument()
  })
})

describe('SupplierDetailPage', () => {
  function renderDetail(role: Role = 'manager') {
    renderWithAuth(<SupplierDetailPage />, {
      auth: loggedInAs(role),
      path: '/suppliers/3',
      route: '/suppliers/:supplierId',
    })
    return userEvent.setup()
  }

  it('shows the supplier and the products it offers', async () => {
    renderDetail()

    expect(
      await screen.findByRole('heading', { name: 'Nordtech Distribution GmbH' }),
    ).toBeInTheDocument()
    expect(screen.getByText('97 %')).toBeInTheDocument()
    await screen.findByRole('link', { name: /LAP-1401/ })
    const offers = screen.getByRole('table', { name: 'Products offered by this supplier' })
    expect(within(offers).getByRole('link', { name: /LAP-1401/ })).toHaveAttribute(
      'href',
      '/products/7',
    )
  })

  it('adds a product, offering only products not yet listed', async () => {
    api.addSupplierProduct.mockResolvedValue(
      makeOffer({ id: 13, product: { id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' } }),
    )
    const user = renderDetail()

    await user.click(await screen.findByRole('button', { name: 'Add product' }))
    const product = await screen.findByRole('combobox', { name: /Product/ })
    await waitFor(() => expect(within(product).getAllByRole('option')).toHaveLength(2))
    expect(within(product).queryByText(/LAP-1401/)).not.toBeInTheDocument() // already offered

    await user.selectOptions(product, 'ACC-MOU1 · Wireless Mouse')
    await user.type(screen.getByRole('textbox', { name: /Unit cost/ }), '9.80')
    await user.click(screen.getByRole('checkbox', { name: /Preferred/ }))
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Add product' }),
    )

    await waitFor(() =>
      expect(api.addSupplierProduct).toHaveBeenCalledWith(3, {
        product_id: 8,
        supplier_sku: null,
        unit_cost: '9.80',
        lead_time_days: null,
        min_order_qty: 1,
        is_preferred: true,
      }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('ACC-MOU1 added to SUP-001')
  })

  it('removes a product after confirmation', async () => {
    api.removeSupplierProduct.mockResolvedValue()
    const user = renderDetail()

    await user.click(await screen.findByRole('button', { name: 'Remove LAP-1401' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(api.removeSupplierProduct).toHaveBeenCalledWith(3, 7))
  })

  it('staff see offers but cannot change them', async () => {
    renderDetail('staff')

    await screen.findByRole('link', { name: /LAP-1401/ })
    expect(screen.queryByRole('button', { name: 'Add product' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove LAP-1401' })).not.toBeInTheDocument()
  })
})
