/** Types mirroring the backend order, shipment and return schemas. */
import type { BinRef, ProductRef, UserRef } from './inventory'

export const ORDER_STATUSES = [
  'created',
  'confirmed',
  'inventory_reserved',
  'partially_allocated',
  'backordered',
  'allocated',
  'picking',
  'picked',
  'packing',
  'packed',
  'shipped',
  'delayed',
  'delivered',
  'returned',
  'on_hold',
  'cancelled',
] as const
export type OrderStatus = (typeof ORDER_STATUSES)[number]

export const ORDER_PRIORITIES = ['low', 'normal', 'high', 'urgent'] as const
export type OrderPriority = (typeof ORDER_PRIORITIES)[number]

export interface CustomerRef {
  id: number
  code: string
  name: string
}

export interface Customer extends CustomerRef {
  customer_type: 'business' | 'consumer'
  email: string | null
  phone: string | null
  address_line: string | null
  postal_code: string | null
  city: string | null
  country: string | null
  user_id: number | null
  is_active: boolean
  created_at: string
}

export interface OrderItem {
  id: number
  line_number: number
  product: ProductRef
  quantity: number
  unit_price: string
  line_total: string
  quantity_reserved: number
  quantity_picked: number
  quantity_packed: number
  quantity_shipped: number
  quantity_returned: number
}

export interface OrderHistoryEntry {
  from_status: OrderStatus | null
  to_status: OrderStatus
  note: string | null
  changed_by: UserRef | null
  created_at: string
}

export interface OrderSummary {
  id: number
  order_number: string
  customer: CustomerRef
  status: OrderStatus
  priority: OrderPriority
  subtotal: string
  total_quantity: number
  requested_delivery_date: string | null
  created_at: string
}

export interface Order extends OrderSummary {
  warehouse: { id: number; code: string; name: string } | null
  ship_to_name: string
  ship_to_address: string | null
  ship_to_postal_code: string | null
  ship_to_city: string | null
  ship_to_country: string | null
  notes: string | null
  confirmed_at: string | null
  shipped_at: string | null
  delivered_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  items: OrderItem[]
  history: OrderHistoryEntry[]
  next_statuses: OrderStatus[]
}

export interface Carrier {
  id: number
  code: string
  name: string
  default_transit_days: number
  is_active: boolean
}

export interface ShipmentEvent {
  id: number
  event_type: string
  occurred_at: string
  location: string | null
  description: string | null
}

export interface Shipment {
  id: number
  order: { id: number; order_number: string; priority: string; status: string }
  carrier: Carrier
  tracking_number: string
  tracking_url: string | null
  status: 'dispatched' | 'in_transit' | 'delayed' | 'delivered' | 'returned'
  package_count: number
  weight_kg: string
  shipped_at: string
  expected_delivery_date: string
  delivered_at: string | null
  events: ShipmentEvent[]
}

export interface ReturnItem {
  id: number
  product: ProductRef
  quantity: number
  condition: 'restock' | 'damaged' | null
  bin: BinRef | null
  note: string | null
}

export interface OrderReturn {
  id: number
  return_number: string
  order_id: number
  order_number: string
  status: 'open' | 'completed' | 'cancelled'
  reason: string
  created_at: string
  completed_at: string | null
  items: ReturnItem[]
}

// -------------------------------------------------------------------- fulfillment
export interface OrderRef {
  id: number
  order_number: string
  priority: OrderPriority
  status: OrderStatus
}

export interface PickingTask {
  id: number
  order: OrderRef
  sequence: number
  product: ProductRef & { barcode: string | null }
  bin: BinRef
  quantity: number
  quantity_picked: number | null
  status: 'pending' | 'in_progress' | 'completed' | 'short' | 'cancelled'
  assigned_to: UserRef | null
  started_at: string | null
  completed_at: string | null
  short_reason: string | null
}

export interface PackingTask {
  id: number
  order: OrderRef
  status: 'pending' | 'in_progress' | 'completed'
  packed_by: UserRef | null
  started_at: string | null
  completed_at: string | null
  package_count: number | null
  weight_kg: string | null
  note: string | null
  lines: { product: ProductRef; quantity_ordered: number; quantity_picked: number }[]
}
