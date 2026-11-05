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

// ------------------------------------------------------------------ operations
export const ADJUSTMENT_KINDS = ['increase', 'decrease', 'damage', 'restore', 'write_off'] as const
export type AdjustmentKind = (typeof ADJUSTMENT_KINDS)[number]

export type DocumentStatus = 'pending' | 'completed' | 'rejected' | 'cancelled'

interface DocumentFields {
  id: number
  created_at: string
  status: DocumentStatus
  product: ProductRef
  quantity: number
  requested_by: UserRef | null
  decided_by: UserRef | null
  decided_at: string | null
  decision_note: string | null
}

export interface StockAdjustment extends DocumentFields {
  bin: BinRef
  kind: AdjustmentKind
  reason: string
}

export interface StockTransfer extends DocumentFields {
  from_bin: BinRef
  to_bin: BinRef
  reason: string | null
}

/** `applied` = done now; false = a request waiting for a manager. */
export interface AdjustmentSubmitResult {
  applied: boolean
  adjustment: StockAdjustment
}

export interface TransferSubmitResult {
  applied: boolean
  transfer: StockTransfer
}

export interface ApprovalQueue {
  adjustments: StockAdjustment[]
  transfers: StockTransfer[]
}

// ---------------------------------------------------------------- cycle counts
export type CycleCountStatus = 'open' | 'submitted' | 'completed' | 'cancelled'

export interface CycleCountLine {
  id: number
  product: ProductRef
  expected_quantity: number
  counted_quantity: number | null
  variance: number | null
}

export interface CycleCountSummary {
  id: number
  created_at: string
  status: CycleCountStatus
  bin: BinRef
  requested_by: UserRef | null
  submitted_at: string | null
}

export interface CycleCount extends CycleCountSummary {
  note: string | null
  decided_by: UserRef | null
  decided_at: string | null
  decision_note: string | null
  lines: CycleCountLine[]
}
