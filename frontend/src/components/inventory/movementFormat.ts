import type { BadgeTone } from '../common/Badge'
import type { CycleCountStatus, Movement, MovementType, ReferenceType } from '../../types/inventory'

export const MOVEMENT_LABELS: Record<MovementType, string> = {
  receipt: 'Received',
  adjustment: 'Adjustment',
  damage: 'Damaged',
  restore: 'Restored',
  write_off: 'Written off',
  transfer_out: 'Moved out',
  transfer_in: 'Moved in',
  reservation: 'Reserved',
  release: 'Released',
  cycle_count: 'Cycle count',
  pick: 'Picked',
  return: 'Returned',
}

export const MOVEMENT_TONES: Record<MovementType, BadgeTone> = {
  receipt: 'success',
  adjustment: 'warning',
  damage: 'danger',
  restore: 'success',
  write_off: 'danger',
  transfer_out: 'info',
  transfer_in: 'info',
  reservation: 'neutral',
  release: 'neutral',
  cycle_count: 'warning',
  pick: 'info',
  return: 'success',
}

const REFERENCE_LABELS: Record<ReferenceType, string> = {
  transfer: 'Transfer',
  adjustment: 'Adjustment',
  reservation: 'Reservation',
  cycle_count: 'Cycle count',
  order: 'Order',
  return: 'Return',
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : `−${Math.abs(value)}` // real minus sign
}

/** e.g. "+4 on hand", "−2 on hand, −2 damaged", "+3 reserved". */
export function describeChange(m: Movement): string {
  const parts: string[] = []
  if (m.on_hand_delta) parts.push(`${signed(m.on_hand_delta)} on hand`)
  if (m.reserved_delta) parts.push(`${signed(m.reserved_delta)} reserved`)
  if (m.damaged_delta) parts.push(`${signed(m.damaged_delta)} damaged`)
  return parts.join(', ')
}

/** Balances right after the movement, e.g. "6 on hand · 4 reserved". */
export function describeBalance(m: Movement): string {
  const parts = [`${m.on_hand_after} on hand`]
  if (m.reserved_after) parts.push(`${m.reserved_after} reserved`)
  if (m.damaged_after) parts.push(`${m.damaged_after} damaged`)
  return parts.join(' · ')
}

/** e.g. "Transfer #12"; null for movements without a document (receipts). */
export function describeReference(m: Movement): string | null {
  if (!m.reference_type || m.reference_id == null) return null
  return `${REFERENCE_LABELS[m.reference_type]} #${m.reference_id}`
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString('en-IE', { dateStyle: 'medium', timeStyle: 'short' })
}

export const COUNT_STATUS_TONES: Record<CycleCountStatus, BadgeTone> = {
  open: 'info',
  submitted: 'warning',
  completed: 'success',
  cancelled: 'neutral',
}
