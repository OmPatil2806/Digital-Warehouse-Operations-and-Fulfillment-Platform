import type { User } from '../../types/auth'
import type { AdjustmentKind, InventoryRow } from '../../types/inventory'
import { hasAnyRole } from '../../utils/roles'

export const MAX_QUANTITY = 1_000_000

export const KIND_LABELS: Record<AdjustmentKind, string> = {
  increase: 'Found units (increase)',
  decrease: 'Missing units (decrease)',
  damage: 'Mark as damaged',
  restore: 'Damaged units are fine (restore)',
  write_off: 'Write off damaged units',
}

/** Adjustments that lose sellable stock: staff need a manager's approval for them. */
export const LOSS_KINDS: readonly AdjustmentKind[] = ['decrease', 'damage', 'write_off']

/** Mirrors app/services/approval_service.py: managers and admins never need approval. */
export function isApprover(user: User | null): boolean {
  return hasAnyRole(user, ['manager'])
}

export function adjustmentNeedsApproval(user: User | null, kind: AdjustmentKind): boolean {
  return !isApprover(user) && LOSS_KINDS.includes(kind)
}

export function warehouseCode(locationCode: string): string {
  return locationCode.split('-')[0]
}

/** How many units an adjustment of this kind can take from a stock row at most. */
export function maxForKind(kind: AdjustmentKind, row: InventoryRow | undefined): number | null {
  if (!row || kind === 'increase') return null
  if (kind === 'restore' || kind === 'write_off') return row.quantity_damaged
  return row.quantity_available // decrease, damage: only good, unreserved units
}

/** Parse a quantity field; returns an error text or the number. */
export function parseQuantity(text: string, max?: number | null): number | string {
  if (!/^\d+$/.test(text.trim())) return 'Enter a whole number'
  const value = Number(text)
  if (value < 1) return 'At least 1'
  if (value > MAX_QUANTITY) return `At most ${MAX_QUANTITY.toLocaleString('en-IE')}`
  if (max != null && value > max) return `Only ${max} possible here`
  return value
}
