import type { ProductRef, UserRef } from './inventory'

export type PurchaseOrderStatus =
  'draft' | 'ordered' | 'partially_received' | 'received' | 'cancelled'

export interface PurchaseOrderItem {
  id: number
  product: ProductRef
  quantity: number
  unit_cost: string
  quantity_received: number
  quantity_outstanding: number
}

export interface PurchaseOrder {
  id: number
  po_number: string
  supplier: { id: number; code: string; name: string }
  warehouse: { id: number; code: string; name: string }
  status: PurchaseOrderStatus
  expected_date: string
  is_overdue: boolean
  notes: string | null
  total_cost: string
  created_by: UserRef | null
  created_at: string
  ordered_at: string | null
  received_at: string | null
  items: PurchaseOrderItem[]
}
