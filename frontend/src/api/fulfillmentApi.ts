import type { Page } from '../types/catalog'
import type { Carrier, PackingTask, PickingTask, Shipment } from '../types/orders'
import { apiClient } from './apiClient'

export const fulfillmentKeys = {
  all: ['fulfillment'] as const,
  picking: (params: object) => ['fulfillment', 'picking', params] as const,
  packing: (status: string) => ['fulfillment', 'packing', status] as const,
  carriers: ['carriers'] as const,
}

export async function listPickingTasks(
  params: { status?: string; mine?: boolean; offset?: number; limit?: number } = {},
): Promise<Page<PickingTask>> {
  const { data } = await apiClient.get<Page<PickingTask>>('/picking-tasks', {
    params: { ...params, mine: params.mine || undefined },
  })
  return data
}

export async function startPicking(id: number): Promise<PickingTask> {
  const { data } = await apiClient.post<PickingTask>(`/picking-tasks/${id}/start`)
  return data
}

export async function completePicking(
  id: number,
  input: { bin_code: string; product_code: string; quantity_picked: number; short_reason?: string },
): Promise<PickingTask> {
  const { data } = await apiClient.post<PickingTask>(`/picking-tasks/${id}/complete`, input)
  return data
}

export async function listPackingTasks(status = 'open'): Promise<Page<PackingTask>> {
  const { data } = await apiClient.get<Page<PackingTask>>('/packing-tasks', {
    params: { status, limit: 100 },
  })
  return data
}

export async function startPacking(id: number): Promise<PackingTask> {
  const { data } = await apiClient.post<PackingTask>(`/packing-tasks/${id}/start`)
  return data
}

export async function completePacking(
  id: number,
  input: {
    items: { product_id: number; quantity: number }[]
    package_count: number
    weight_kg: string
    note?: string
  },
): Promise<PackingTask> {
  const { data } = await apiClient.post<PackingTask>(`/packing-tasks/${id}/complete`, input)
  return data
}

export async function listCarriers(): Promise<Carrier[]> {
  const { data } = await apiClient.get<Carrier[]>('/carriers')
  return data
}

export async function createShipment(input: {
  order_id: number
  carrier_id: number
  tracking_number?: string
  expected_delivery_date?: string
}): Promise<Shipment> {
  const { data } = await apiClient.post<Shipment>('/shipments', input)
  return data
}
