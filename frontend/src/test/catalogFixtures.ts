import type { Category, Page, Product, Supplier, SupplierProduct } from '../types/catalog'

export function page<T>(items: T[], total = items.length, offset = 0, limit = 25): Page<T> {
  return { items, total, offset, limit }
}

export function makeCategory(overrides: Partial<Category> = {}): Category {
  return {
    id: 1,
    name: 'Laptops',
    description: null,
    parent_id: null,
    is_active: true,
    product_count: 1,
    created_at: '2026-11-01T08:00:00Z',
    updated_at: '2026-11-01T08:00:00Z',
    ...overrides,
  }
}

export function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    id: 7,
    sku: 'LAP-1401',
    name: 'Laptop 14" Business',
    description: null,
    category: { id: 1, name: 'Laptops' },
    brand: 'Vantec',
    unit_price: '899.00',
    unit_cost: '640.00',
    margin: '259.00',
    weight_kg: '1.450',
    length_cm: '33.0',
    width_cm: '23.5',
    height_cm: '2.0',
    volume_cm3: '1551.000',
    barcode: '4000000000017',
    min_stock: 5,
    max_stock: 40,
    default_supplier: { id: 3, name: 'Nordtech Distribution GmbH', code: 'SUP-001' },
    is_active: true,
    created_at: '2026-11-01T08:00:00Z',
    updated_at: '2026-11-01T08:00:00Z',
    ...overrides,
  }
}

export function makeSupplier(overrides: Partial<Supplier> = {}): Supplier {
  return {
    id: 3,
    code: 'SUP-001',
    name: 'Nordtech Distribution GmbH',
    contact_name: null,
    email: 'orders@example.com',
    phone: null,
    address: null,
    country: 'Germany',
    lead_time_days: 5,
    reliability_score: '0.97',
    is_active: true,
    created_at: '2026-11-01T08:00:00Z',
    updated_at: '2026-11-01T08:00:00Z',
    ...overrides,
  }
}

export function makeOffer(overrides: Partial<SupplierProduct> = {}): SupplierProduct {
  return {
    id: 11,
    supplier: { id: 3, name: 'Nordtech Distribution GmbH', code: 'SUP-001' },
    product: { id: 7, name: 'Laptop 14" Business', sku: 'LAP-1401' },
    supplier_sku: '001-LAP-1401',
    unit_cost: '640.00',
    lead_time_days: null,
    effective_lead_time_days: 5,
    min_order_qty: 2,
    is_preferred: true,
    ...overrides,
  }
}
