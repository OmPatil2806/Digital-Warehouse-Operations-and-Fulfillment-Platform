import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import * as inventoryApi from '../api/inventoryApi'
import { makeCategory, makeOffer, makeProduct, makeSupplier, page } from '../test/catalogFixtures'
import { makeProductStock } from '../test/inventoryFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import ProductDetailPage from './ProductDetailPage'

vi.mock('../api/catalogApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/catalogApi')>()),
  getProduct: vi.fn(),
  getProductSuppliers: vi.fn(),
  updateProduct: vi.fn(),
  listCategories: vi.fn(),
  listSuppliers: vi.fn(),
}))
vi.mock('../api/inventoryApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/inventoryApi')>()),
  getProductStock: vi.fn(),
}))
const api = vi.mocked(catalogApi)

beforeEach(() => {
  vi.clearAllMocks()
  api.getProduct.mockResolvedValue(makeProduct())
  api.getProductSuppliers.mockResolvedValue([
    makeOffer(),
    makeOffer({
      id: 12,
      supplier: { id: 9, code: 'SUP-009', name: 'Danube Electronics Kft' },
      is_preferred: false,
      unit_cost: '691.20',
    }),
  ])
  api.listCategories.mockResolvedValue(page([makeCategory()]))
  api.listSuppliers.mockResolvedValue(page([makeSupplier()]))
  vi.mocked(inventoryApi.getProductStock).mockResolvedValue(makeProductStock())
})

function renderPage(role: Role = 'manager', id = '7') {
  renderWithAuth(<ProductDetailPage />, {
    auth: loggedInAs(role),
    path: `/products/${id}`,
    route: '/products/:productId',
  })
  return userEvent.setup()
}

describe('ProductDetailPage', () => {
  it('shows where the product is stored', async () => {
    renderPage('staff')

    const stock = await screen.findByRole('region', { name: 'Stock' })
    const bins = within(stock).getByRole('table', { name: 'Bins holding this product' })
    expect(await within(bins).findByText('WH01-ZA-R01-S01-B01')).toBeInTheDocument()
    expect(within(bins).getByText('WH01-ZB-R01-S01-B01')).toBeInTheDocument()
    expect(within(stock).getByRole('link', { name: /Movement history/ })).toHaveAttribute(
      'href',
      '/inventory?view=movements&product=7',
    )
    expect(inventoryApi.getProductStock).toHaveBeenCalledWith(7)
  })

  it('shows the product details and its suppliers', async () => {
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Laptop 14" Business' })).toBeInTheDocument()
    expect(screen.getByText('€640.00', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByText('33 × 23.5 × 2 cm')).toBeInTheDocument()
    expect(screen.getByText('min 5 · max 40')).toBeInTheDocument()
    await screen.findByText('€691.20')
    const offers = screen.getByRole('table', { name: 'Suppliers offering this product' })
    expect(within(offers).getByRole('link', { name: /SUP-001/ })).toHaveAttribute(
      'href',
      '/suppliers/3',
    )
    expect(within(offers).getByText('Preferred')).toBeInTheDocument()
    expect(within(offers).getByText('€691.20')).toBeInTheDocument()
  })

  it('archives after confirmation', async () => {
    api.updateProduct.mockResolvedValue(makeProduct({ is_active: false }))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Archive' }))
    const dialog = screen.getByRole('dialog', { name: 'Archive LAP-1401?' })
    await user.click(within(dialog).getByRole('button', { name: 'Archive' }))

    await waitFor(() => expect(api.updateProduct).toHaveBeenCalledWith(7, { is_active: false }))
    expect(await screen.findByRole('status')).toHaveTextContent('LAP-1401 archived')
  })

  it('cancelling the confirmation changes nothing', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Archive' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(api.updateProduct).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens the edit form pre-filled, with the current category selected', async () => {
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit' }))

    const dialog = await screen.findByRole('dialog', { name: 'Edit LAP-1401' })
    expect(within(dialog).getByRole('textbox', { name: /SKU/ })).toHaveValue('LAP-1401')
    expect(within(dialog).getByRole('textbox', { name: /Selling price/ })).toHaveValue('899.00')
    expect(within(dialog).getByRole('combobox', { name: /Category/ })).toHaveValue('1')
    expect(within(dialog).getByRole('combobox', { name: /Default supplier/ })).toHaveValue('3')
  })

  it('staff see the details but no Edit or Archive buttons', async () => {
    renderPage('staff')

    await screen.findByRole('heading', { name: 'Laptop 14" Business' })
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
  })

  it('archived products offer Restore instead', async () => {
    api.getProduct.mockResolvedValue(makeProduct({ is_active: false }))
    renderPage()

    expect(await screen.findByRole('button', { name: 'Restore' })).toBeInTheDocument()
    expect(screen.getByText('Archived')).toBeInTheDocument()
  })

  it('shows the 404 page for unknown products', async () => {
    const response = {
      status: 404,
      data: { detail: 'Product not found' },
      statusText: '',
      headers: {},
      config: { headers: new AxiosHeaders() },
    } as AxiosResponse
    api.getProduct.mockRejectedValue(new AxiosError('nf', 'ERR', undefined, undefined, response))
    renderPage('manager', '999')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
