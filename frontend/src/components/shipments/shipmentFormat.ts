import type { BadgeTone } from '../common/Badge'
import type { OrderReturn, Shipment } from '../../types/orders'

export const EVENT_LABELS = {
  created: 'Created',
  dispatched: 'Dispatched',
  in_transit: 'In transit',
  out_for_delivery: 'Out for delivery',
  delayed: 'Delayed',
  delivered: 'Delivered',
  exception: 'Exception',
  returned: 'Returned',
} as const

export const SHIPMENT_TONES: Record<Shipment['status'], BadgeTone> = {
  dispatched: 'info',
  in_transit: 'info',
  delayed: 'danger',
  delivered: 'success',
  returned: 'neutral',
}

export const RETURN_TONES: Record<OrderReturn['status'], BadgeTone> = {
  open: 'warning',
  completed: 'success',
  cancelled: 'neutral',
}
