import type { StockStatus } from '../../types/dashboard'
import { STATUS, type StatusTone } from './chartTheme'

/** Stock status of a product as words, a status tone and its colour. */
export const STOCK_STATUS: Record<StockStatus, { label: string; tone: StatusTone }> = {
  ok: { label: 'In stock', tone: 'good' },
  low: { label: 'Below minimum', tone: 'warning' },
  out: { label: 'Out of stock', tone: 'critical' },
}

export function stockStatusColor(status: StockStatus): string {
  return STATUS[STOCK_STATUS[status].tone]
}
