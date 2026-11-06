import type { Page } from '../types/catalog'
import type { PurchaseOrder } from '../types/purchasing'
import { apiClient } from './apiClient'

export const purchaseOrderKeys = {
  all: ['purchase-orders'] as const,
  list: (params: object) => ['purchase-orders', 'list', params] as const,
}

export async function listPurchaseOrders(
  params: { q?: string; status?: string; overdue?: boolean; offset?: number; limit?: number } = {},
): Promise<Page<PurchaseOrder>> {
  const { data } = await apiClient.get<Page<PurchaseOrder>>('/purchase-orders', {
    params: {
      q: params.q || undefined,
      status: params.status || undefined,
      overdue: params.overdue || undefined,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}

export async function createPurchaseOrder(input: {
  supplier_id: number
  warehouse_id: number
  expected_date?: string
  notes?: string
  items: { product_id: number; quantity: number; unit_cost?: string }[]
}): Promise<PurchaseOrder> {
  const { data } = await apiClient.post<PurchaseOrder>('/purchase-orders', input)
  return data
}

export async function purchaseOrderAction(
  id: number,
  action: 'order' | 'cancel',
): Promise<PurchaseOrder> {
  const { data } = await apiClient.post<PurchaseOrder>(`/purchase-orders/${id}/${action}`)
  return data
}

export async function receivePurchaseOrder(
  id: number,
  items: { product_id: number; quantity: number; bin_id: number }[],
): Promise<PurchaseOrder> {
  const { data } = await apiClient.post<PurchaseOrder>(`/purchase-orders/${id}/receive`, { items })
  return data
}

export async function checkOverduePurchaseOrders(): Promise<PurchaseOrder[]> {
  const { data } = await apiClient.post<PurchaseOrder[]>('/purchase-orders/check-overdue')
  return data
}
