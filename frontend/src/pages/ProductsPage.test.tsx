import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as catalogApi from '../api/catalogApi'
import { makeCategory, makeProduct, makeSupplier, page } from '../test/catalogFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import type { Role } from '../types/auth'
import ProductsPage from './ProductsPage'

vi.mock('../api/catalogApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/catalogApi')>()
  return {
    ...actual, // keep catalogKeys
    listProducts: vi.fn(),
    listCategories: vi.fn(),
    listSuppliers: vi.fn(),
    createProduct: vi.fn(),
  }
})
const api = vi.mocked(catalogApi)

function conflict(detail: string): AxiosError {
  const response = {
    status: 409,
    data: { detail },
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('conflict', 'ERR_BAD_REQUEST', undefined, undefined, response)
}

const LAPTOP = makeProduct()
const MOUSE = makeProduct({
  id: 8,
  sku: 'ACC-MOU1',
  name: 'Wireless Mouse',
  unit_price: '24.90',
  margin: '-1.00',
  category: { id: 2, name: 'Accessories' },
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listProducts.mockResolvedValue(page([LAPTOP, MOUSE], 60))
  api.listCategories.mockResolvedValue(
    page([makeCategory(), makeCategory({ id: 2, name: 'Accessories' })]),
  )
  api.listSuppliers.mockResolvedValue(page([makeSupplier()]))
})

function renderPage(role: Role = 'manager', path = '/products') {
  renderWithAuth(<ProductsPage />, {
    auth: loggedInAs(role),
    path,
    route: '/products',
    routes: { '/products/:id': <p>detail page</p> },
  })
  return userEvent.setup()
}

const location = () => screen.getByTestId('location').textContent

describe('ProductsPage', () => {
  it('lists products with formatted prices and margins', async () => {
    renderPage()

    await screen.findByText('LAP-1401') // the table appears at once, the rows when loaded
    const table = screen.getByRole('table', { name: 'Products' })
    expect(within(table).getByText('€899.00')).toBeInTheDocument()
    expect(within(table).getByText('-€1.00')).toHaveClass('text-red-600') // sold at a loss
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toHaveTextContent(
      'Showing 1–25 of 60',
    )
    expect(api.listProducts).toHaveBeenCalledWith({
      q: undefined,
      categoryId: undefined,
      status: 'active',
      sort: 'sku',
      offset: 0,
      limit: 25,
    })
  })

  it('reads filters from the URL (bookmarks and shared links work)', async () => {
    renderPage('manager', '/products?q=lap&category=2&status=all&sort=-unit_price&offset=25')

    await screen.findByText('LAP-1401')
    expect(api.listProducts).toHaveBeenCalledWith({
      q: 'lap',
      categoryId: 2,
      status: 'all',
      sort: '-unit_price',
      offset: 25,
      limit: 25,
    })
    expect(screen.getByRole('searchbox', { name: 'Search products' })).toHaveValue('lap')
  })

  it('writes sort, filters and page to the URL', async () => {
    const user = renderPage()
    await screen.findByText('LAP-1401')

    await user.click(screen.getByRole('button', { name: /Price/ }))
    expect(location()).toBe('/products?sort=unit_price')

    await user.click(screen.getByRole('button', { name: /Next/ }))
    expect(location()).toBe('/products?sort=unit_price&offset=25')

    await user.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'Accessories')
    expect(location()).toBe('/products?sort=unit_price&category=2') // filters reset the page

    await user.type(screen.getByRole('searchbox', { name: 'Search products' }), 'mouse')
    await waitFor(() => expect(location()).toContain('q=mouse'))
  })

  it('opens the detail page when a row is clicked', async () => {
    const user = renderPage()

    await user.click(await screen.findByText('Wireless Mouse'))

    expect(location()).toBe('/products/8')
  })

  it('shows a retry button when loading fails', async () => {
    api.listProducts.mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
    const user = renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the server')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('LAP-1401')).toBeInTheDocument()
  })

  it('staff can browse but get no "New product" button', async () => {
    renderPage('staff')

    await screen.findByText('LAP-1401')
    expect(screen.queryByRole('button', { name: 'New product' })).not.toBeInTheDocument()
  })

  describe('creating a product', () => {
    async function openForm() {
      const user = renderPage()
      await user.click(await screen.findByRole('button', { name: 'New product' }))
      // wait until the dropdown options have loaded and the form is shown
      const form = await screen.findByRole('dialog', { name: 'New product' })
      await within(form).findByRole('button', { name: 'Create product' })
      return user
    }

    const dialog = () => within(screen.getByRole('dialog'))

    async function fillValid(user: ReturnType<typeof userEvent.setup>) {
      await user.type(screen.getByRole('textbox', { name: /SKU/ }), 'tab-1001')
      await user.type(screen.getByRole('textbox', { name: /^Name/ }), 'Tablet 11"')
      await user.selectOptions(dialog().getByRole('combobox', { name: /Category/ }), 'Laptops')
      await user.type(screen.getByRole('textbox', { name: /Selling price/ }), '449')
      await user.type(screen.getByRole('textbox', { name: /Purchase cost/ }), '300.50')
      await user.type(screen.getByRole('textbox', { name: /Weight/ }), '0.55')
      await user.type(screen.getByRole('textbox', { name: /Length/ }), '25')
      await user.type(screen.getByRole('textbox', { name: /Width/ }), '17')
      await user.type(screen.getByRole('textbox', { name: /Height/ }), '0.8')
    }

    it('validates fields before sending anything', async () => {
      const user = await openForm()

      await user.type(screen.getByRole('textbox', { name: /Selling price/ }), '1.999')
      await user.type(screen.getByRole('textbox', { name: /Weight/ }), '0')
      await user.type(screen.getByRole('textbox', { name: /^Max stock/ }), '2')
      await user.clear(screen.getByRole('textbox', { name: /^Min stock/ }))
      await user.type(screen.getByRole('textbox', { name: /^Min stock/ }), '5')
      await user.click(screen.getByRole('button', { name: 'Create product' }))

      expect(await screen.findByText('SKU must have at least 2 characters')).toBeInTheDocument()
      expect(screen.getByText('Choose a category')).toBeInTheDocument()
      expect(screen.getByText('Enter a number with at most 2 decimal places')).toBeInTheDocument()
      expect(screen.getByText('Weight must be greater than 0')).toBeInTheDocument()
      expect(screen.getByText('Max stock must be at least the min stock')).toBeInTheDocument()
      expect(api.createProduct).not.toHaveBeenCalled()
    })

    it('warns (but allows) a selling price below cost', async () => {
      const user = await openForm()

      await user.type(screen.getByRole('textbox', { name: /Selling price/ }), '10')
      await user.type(screen.getByRole('textbox', { name: /Purchase cost/ }), '12')

      expect(screen.getByRole('status')).toHaveTextContent('sold at a loss')
    })

    it('sends exact decimal strings and opens the new product', async () => {
      api.createProduct.mockResolvedValue(makeProduct({ id: 99, sku: 'TAB-1001' }))
      const user = await openForm()

      await fillValid(user)
      await user.click(screen.getByRole('button', { name: 'Create product' }))

      await waitFor(() => expect(location()).toBe('/products/99'))
      expect(api.createProduct).toHaveBeenCalledWith({
        sku: 'tab-1001',
        name: 'Tablet 11"',
        category_id: 1,
        brand: null,
        description: null,
        unit_price: '449',
        unit_cost: '300.50',
        weight_kg: '0.55',
        length_cm: '25',
        width_cm: '17',
        height_cm: '0.8',
        barcode: null,
        min_stock: 0,
        max_stock: null,
        default_supplier_id: null,
      })
      expect(screen.getByRole('status')).toHaveTextContent('Product TAB-1001 created')
    })

    it('shows "SKU already exists" under the SKU field', async () => {
      api.createProduct.mockRejectedValue(conflict('A product with this SKU already exists'))
      const user = await openForm()

      await fillValid(user)
      await user.click(screen.getByRole('button', { name: 'Create product' }))

      const sku = screen.getByRole('textbox', { name: /SKU/ })
      await waitFor(() =>
        expect(sku).toHaveAccessibleDescription('A product with this SKU already exists'),
      )
      expect(screen.getByRole('dialog')).toBeInTheDocument() // stays open to fix the value
    })
  })
})
