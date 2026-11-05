/** Types mirroring the backend inventory schemas (app/schemas/inventory.py). */

export interface ProductRef {
  id: number
  sku: string
  name: string
}

export interface BinRef {
  id: number
  location_code: string
}

export interface UserRef {
  id: number
  full_name: string
  email: string
}

/** Stock of one product in one bin. available = on hand - reserved - damaged. */
export interface InventoryRow {
  id: number
  product: ProductRef
  bin: BinRef
  quantity_on_hand: number
  quantity_reserved: number
  quantity_damaged: number
  quantity_available: number
  updated_at: string
}

export interface ProductStock {
  product: ProductRef
  min_stock: number
  quantity_on_hand: number
  quantity_reserved: number
  quantity_damaged: number
  quantity_available: number
  is_low_stock: boolean
  bins: InventoryRow[]
}

export const MOVEMENT_TYPES = [
  'receipt',
  'adjustment',
  'damage',
  'restore',
  'write_off',
  'transfer_out',
  'transfer_in',
  'reservation',
  'release',
  'cycle_count',
  'pick',
  'return',
] as const
export type MovementType = (typeof MOVEMENT_TYPES)[number]

export type ReferenceType =
  'transfer' | 'adjustment' | 'reservation' | 'cycle_count' | 'order' | 'return'

export interface Movement {
  id: number
  created_at: string
  movement_type: MovementType
  product: ProductRef
  bin: BinRef
  quantity: number
  on_hand_delta: number
  reserved_delta: number
  damaged_delta: number
  on_hand_after: number
  reserved_after: number
  damaged_after: number
  reference_type: ReferenceType | null
  reference_id: number | null
  reason: string | null
  created_by: UserRef | null
}
