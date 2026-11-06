import type { Page } from '../types/catalog'
import type { Carrier, OrderReturn, PackingTask, PickingTask, Shipment } from '../types/orders'
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

// --------------------------------------------------------------------- shipments
export const shipmentKeys = {
  all: ['shipments'] as const,
  list: (params: object) => ['shipments', 'list', params] as const,
}

export async function listShipments(
  params: { status?: string; q?: string; offset?: number; limit?: number } = {},
): Promise<Page<Shipment>> {
  const { data } = await apiClient.get<Page<Shipment>>('/shipments', {
    params: { ...params, q: params.q || undefined, status: params.status || undefined },
  })
  return data
}

export type TrackingEventType =
  'in_transit' | 'out_for_delivery' | 'delayed' | 'delivered' | 'exception'

export async function addShipmentEvent(
  id: number,
  input: { event_type: TrackingEventType; location?: string; description?: string },
): Promise<Shipment> {
  const { data } = await apiClient.post<Shipment>(`/shipments/${id}/events`, input)
  return data
}

export async function checkDelays(): Promise<Shipment[]> {
  const { data } = await apiClient.post<Shipment[]>('/shipments/check-delays')
  return data
}

// ----------------------------------------------------------------------- returns
export const returnKeys = {
  all: ['returns'] as const,
  list: (params: object) => ['returns', 'list', params] as const,
}

export async function listReturns(
  params: { status?: string; order_id?: number; offset?: number; limit?: number } = {},
): Promise<Page<OrderReturn>> {
  const { data } = await apiClient.get<Page<OrderReturn>>('/returns', {
    params: { ...params, status: params.status || undefined },
  })
  return data
}

export async function openReturn(input: {
  order_id: number
  reason: string
  items: { product_id: number; quantity: number }[]
}): Promise<OrderReturn> {
  const { data } = await apiClient.post<OrderReturn>('/returns', input)
  return data
}

export async function inspectReturn(
  id: number,
  items: { product_id: number; condition: 'restock' | 'damaged'; note?: string }[],
): Promise<OrderReturn> {
  const { data } = await apiClient.post<OrderReturn>(`/returns/${id}/inspect`, { items })
  return data
}

export async function cancelReturn(id: number): Promise<OrderReturn> {
  const { data } = await apiClient.post<OrderReturn>(`/returns/${id}/cancel`)
  return data
}
