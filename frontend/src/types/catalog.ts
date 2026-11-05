/** Types mirroring the backend catalog schemas. Decimals arrive as strings ("899.99"). */

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export interface Reference {
  id: number
  name: string
}

export interface SupplierReference extends Reference {
  code: string
}

export interface ProductReference extends Reference {
  sku: string
}

export interface Category {
  id: number
  name: string
  description: string | null
  parent_id: number | null
  is_active: boolean
  product_count: number
  created_at: string
  updated_at: string
}

/** Full product (warehouse roles). Customers receive the same without cost fields. */
export interface Product {
  id: number
  sku: string
  name: string
  description: string | null
  category: Reference
  brand: string | null
  unit_price: string
  unit_cost?: string
  margin?: string
  weight_kg: string
  length_cm: string
  width_cm: string
  height_cm: string
  volume_cm3: string
  barcode: string | null
  min_stock?: number
  max_stock?: number | null
  default_supplier?: SupplierReference | null
  is_active: boolean
  created_at?: string
  updated_at?: string
}

export interface ProductInput {
  sku: string
  name: string
  description: string | null
  category_id: number
  brand: string | null
  unit_price: string
  unit_cost: string
  weight_kg: string
  length_cm: string
  width_cm: string
  height_cm: string
  barcode: string | null
  min_stock: number
  max_stock: number | null
  default_supplier_id: number | null
}

export interface Supplier {
  id: number
  code: string
  name: string
  contact_name: string | null
  email: string | null
  phone: string | null
  address: string | null
  country: string | null
  lead_time_days: number
  reliability_score: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SupplierInput {
  code: string
  name: string
  contact_name: string | null
  email: string | null
  phone: string | null
  address: string | null
  country: string | null
  lead_time_days: number
  reliability_score: string
}

export interface SupplierProduct {
  id: number
  supplier: SupplierReference
  product: ProductReference
  supplier_sku: string | null
  unit_cost: string
  lead_time_days: number | null
  effective_lead_time_days: number
  min_order_qty: number
  is_preferred: boolean
}

export interface SupplierProductInput {
  product_id: number
  supplier_sku: string | null
  unit_cost: string
  lead_time_days: number | null
  min_order_qty: number
  is_preferred: boolean
}

export type ActiveFilter = 'active' | 'archived' | 'all'
