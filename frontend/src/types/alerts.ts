/** Types mirroring the backend alert and audit schemas. */
import type { BinRef, ProductRef, UserRef } from './inventory'

export const ALERT_TYPES = [
  'low_stock',
  'over_capacity',
  'predicted_stockout',
  'delay_risk',
  'overdue_supplier',
] as const
export type AlertType = (typeof ALERT_TYPES)[number]
export type AlertSeverity = 'info' | 'warning' | 'critical'
export type AlertStatus = 'open' | 'acknowledged' | 'resolved'

export interface Alert {
  id: number
  created_at: string
  updated_at: string
  alert_type: AlertType
  severity: AlertSeverity
  status: AlertStatus
  title: string
  message: string | null
  product: ProductRef | null
  bin: BinRef | null
  acknowledged_by: UserRef | null
  acknowledged_at: string | null
  resolved_by: UserRef | null
  resolved_at: string | null
}

/** {"field": {"old": ..., "new": ...}}; "create" has only "new", "delete" only "old". */
export type AuditChanges = Record<string, { old?: unknown; new?: unknown } | unknown>

export interface AuditLogEntry {
  id: number
  created_at: string
  actor_id: number | null
  actor_email: string | null
  action: string
  entity_type: string
  entity_id: number | null
  summary: string | null
  changes: AuditChanges | null
}
