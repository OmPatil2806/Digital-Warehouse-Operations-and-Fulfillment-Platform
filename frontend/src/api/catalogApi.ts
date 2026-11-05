import type {
  ActiveFilter,
  Category,
  Page,
  Product,
  ProductInput,
  Supplier,
  SupplierInput,
  SupplierProduct,
  SupplierProductInput,
} from '../types/catalog'
import { apiClient } from './apiClient'

/** Query keys: mutations invalidate these prefixes to reload the right lists. */
export const catalogKeys = {
  categories: ['categories'] as const,
  products: ['products'] as const,
  product: (id: number) => ['products', id] as const,
  productSuppliers: (id: number) => ['products', id, 'suppliers'] as const,
  suppliers: ['suppliers'] as const,
  supplier: (id: number) => ['suppliers', id] as const,
  supplierProducts: (id: number) => ['suppliers', id, 'products'] as const,
}

function activeParam(filter: ActiveFilter | undefined): boolean | undefined {
  if (filter === 'active') return true
  if (filter === 'archived') return false
  return undefined
}

/** Remove empty values so they are not sent as `?q=` etc. */
function clean(params: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== '',
    ),
  )
}

// ---------------------------------------------------------------------------- categories
export async function listCategories(): Promise<Page<Category>> {
  const { data } = await apiClient.get<Page<Category>>('/categories', { params: { limit: 500 } })
  return data
}

// ------------------------------------------------------------------------------ products
export interface ProductListParams {
  q?: string
  categoryId?: number
  supplierId?: number
  status?: ActiveFilter
  sort?: string
  offset?: number
  limit?: number
}

export async function listProducts(params: ProductListParams = {}): Promise<Page<Product>> {
  const { data } = await apiClient.get<Page<Product>>('/products', {
    params: clean({
      q: params.q,
      category_id: params.categoryId,
      supplier_id: params.supplierId,
      is_active: activeParam(params.status),
      sort: params.sort,
      offset: params.offset,
      limit: params.limit,
    }),
  })
  return data
}

export async function getProduct(id: number): Promise<Product> {
  const { data } = await apiClient.get<Product>(`/products/${id}`)
  return data
}

export async function createProduct(input: ProductInput): Promise<Product> {
  const { data } = await apiClient.post<Product>('/products', input)
  return data
}

export async function updateProduct(
  id: number,
  changes: Partial<ProductInput> & { is_active?: boolean },
): Promise<Product> {
  const { data } = await apiClient.patch<Product>(`/products/${id}`, changes)
  return data
}

export async function getProductSuppliers(id: number): Promise<SupplierProduct[]> {
  const { data } = await apiClient.get<SupplierProduct[]>(`/products/${id}/suppliers`)
  return data
}

// ----------------------------------------------------------------------------- suppliers
export interface SupplierListParams {
  q?: string
  status?: ActiveFilter
  sort?: string
  offset?: number
  limit?: number
}

export async function listSuppliers(params: SupplierListParams = {}): Promise<Page<Supplier>> {
  const { data } = await apiClient.get<Page<Supplier>>('/suppliers', {
    params: clean({
      q: params.q,
      is_active: activeParam(params.status),
      sort: params.sort,
      offset: params.offset,
      limit: params.limit,
    }),
  })
  return data
}

export async function getSupplier(id: number): Promise<Supplier> {
  const { data } = await apiClient.get<Supplier>(`/suppliers/${id}`)
  return data
}

export async function createSupplier(input: SupplierInput): Promise<Supplier> {
  const { data } = await apiClient.post<Supplier>('/suppliers', input)
  return data
}

export async function updateSupplier(
  id: number,
  changes: Partial<SupplierInput> & { is_active?: boolean },
): Promise<Supplier> {
  const { data } = await apiClient.patch<Supplier>(`/suppliers/${id}`, changes)
  return data
}

export async function getSupplierProducts(id: number): Promise<SupplierProduct[]> {
  const { data } = await apiClient.get<SupplierProduct[]>(`/suppliers/${id}/products`)
  return data
}

export async function addSupplierProduct(
  supplierId: number,
  input: SupplierProductInput,
): Promise<SupplierProduct> {
  const { data } = await apiClient.post<SupplierProduct>(`/suppliers/${supplierId}/products`, input)
  return data
}

export async function removeSupplierProduct(supplierId: number, productId: number): Promise<void> {
  await apiClient.delete(`/suppliers/${supplierId}/products/${productId}`)
}
