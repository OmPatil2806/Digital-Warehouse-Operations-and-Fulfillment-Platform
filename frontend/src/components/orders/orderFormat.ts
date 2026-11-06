import type { User } from '../../types/auth'
import type { OrderPriority, OrderStatus } from '../../types/orders'
import { hasAnyRole } from '../../utils/roles'
import type { BadgeTone } from '../common/Badge'

export const STATUS_LABELS: Record<OrderStatus, string> = {
  created: 'Created',
  confirmed: 'Confirmed',
  inventory_reserved: 'Reserved',
  partially_allocated: 'Partly reserved',
  backordered: 'Backordered',
  allocated: 'Ready to pick',
  picking: 'Picking',
  picked: 'Picked',
  packing: 'Packing',
  packed: 'Packed',
  shipped: 'Shipped',
  delayed: 'Delayed',
  delivered: 'Delivered',
  returned: 'Returned',
  on_hold: 'On hold',
  cancelled: 'Cancelled',
}

export const STATUS_TONES: Record<OrderStatus, BadgeTone> = {
  created: 'neutral',
  confirmed: 'info',
  inventory_reserved: 'info',
  partially_allocated: 'warning',
  backordered: 'warning',
  allocated: 'info',
  picking: 'info',
  picked: 'info',
  packing: 'info',
  packed: 'info',
  shipped: 'success',
  delayed: 'danger',
  delivered: 'success',
  returned: 'neutral',
  on_hold: 'warning',
  cancelled: 'neutral',
}

export const PRIORITY_TONES: Record<OrderPriority, BadgeTone> = {
  low: 'neutral',
  normal: 'neutral',
  high: 'warning',
  urgent: 'danger',
}

/** Managers and admins handle every order; customers their own; staff fulfil. */
export function isOrderManager(user: User | null): boolean {
  return hasAnyRole(user, ['manager'])
}

export function isWarehouseRole(user: User | null): boolean {
  return hasAnyRole(user, ['manager', 'staff'])
}

/** A customer login (not also a warehouse role): orders only for itself. */
export function isCustomerOnly(user: User | null): boolean {
  return !!user && !isWarehouseRole(user) && user.roles.includes('customer')
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-IE', { dateStyle: 'medium' })
}
