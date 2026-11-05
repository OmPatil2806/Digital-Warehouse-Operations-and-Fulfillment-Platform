import type { InventoryRow, Movement, ProductStock } from '../types/inventory'

export function makeRow(overrides: Partial<InventoryRow> = {}): InventoryRow {
  return {
    id: 1,
    product: { id: 7, sku: 'LAP-1401', name: 'Laptop 14" Business' },
    bin: { id: 20, location_code: 'WH01-ZA-R01-S01-B01' },
    quantity_on_hand: 10,
    quantity_reserved: 2,
    quantity_damaged: 1,
    quantity_available: 7,
    updated_at: '2026-11-05T10:00:00Z',
    ...overrides,
  }
}

export function makeProductStock(overrides: Partial<ProductStock> = {}): ProductStock {
  return {
    product: { id: 7, sku: 'LAP-1401', name: 'Laptop 14" Business' },
    min_stock: 5,
    quantity_on_hand: 14,
    quantity_reserved: 2,
    quantity_damaged: 1,
    quantity_available: 11,
    is_low_stock: false,
    bins: [
      makeRow(),
      makeRow({
        id: 2,
        bin: { id: 21, location_code: 'WH01-ZB-R01-S01-B01' },
        quantity_on_hand: 4,
        quantity_reserved: 0,
        quantity_damaged: 0,
        quantity_available: 4,
      }),
    ],
    ...overrides,
  }
}

export function makeMovement(overrides: Partial<Movement> = {}): Movement {
  return {
    id: 1,
    created_at: '2026-11-05T10:00:00Z',
    movement_type: 'receipt',
    product: { id: 7, sku: 'LAP-1401', name: 'Laptop 14" Business' },
    bin: { id: 20, location_code: 'WH01-ZA-R01-S01-B01' },
    quantity: 10,
    on_hand_delta: 10,
    reserved_delta: 0,
    damaged_delta: 0,
    on_hand_after: 10,
    reserved_after: 0,
    damaged_after: 0,
    reference_type: null,
    reference_id: null,
    reason: 'PO-1001',
    created_by: { id: 3, full_name: 'Sam Staff', email: 'staff@example.com' },
    ...overrides,
  }
}
