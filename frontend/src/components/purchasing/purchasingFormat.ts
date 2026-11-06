import type { PurchaseOrderStatus } from '../../types/purchasing'
import type { BadgeTone } from '../common/Badge'

export const PO_STATUS_LABELS: Record<PurchaseOrderStatus, string> = {
  draft: 'Draft',
  ordered: 'Ordered',
  partially_received: 'Partially received',
  received: 'Received',
  cancelled: 'Cancelled',
}

export const PO_TONES: Record<PurchaseOrderStatus, BadgeTone> = {
  draft: 'neutral',
  ordered: 'info',
  partially_received: 'warning',
  received: 'success',
  cancelled: 'neutral',
}
