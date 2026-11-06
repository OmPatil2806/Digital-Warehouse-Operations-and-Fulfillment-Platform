import type { Page } from '../types/catalog'
import type {
  Customer,
  Order,
  OrderPriority,
  OrderReturn,
  OrderStatus,
  OrderSummary,
  Shipment,
} from '../types/orders'
import { apiClient } from './apiClient'

export const orderKeys = {
  all: ['orders'] as const,
  list: (params: object) => ['orders', 'list', params] as const,
  detail: (id: number) => ['orders', id] as const,
  shipment: (id: number) => ['orders', id, 'shipment'] as const,
  returns: (id: number) => ['orders', id, 'returns'] as const,
  customers: (q: string) => ['customers', q] as const,
  myCustomer: ['customers', 'me'] as const,
}

export interface OrderListParams {
  q?: string
  status?: OrderStatus
  customerId?: number
  offset?: number
  limit?: number
}

export async function listOrders(params: OrderListParams = {}): Promise<Page<OrderSummary>> {
  const { data } = await apiClient.get<Page<OrderSummary>>('/orders', {
    params: {
      q: params.q || undefined,
      status: params.status,
      customer_id: params.customerId,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}

export async function getOrder(id: number): Promise<Order> {
  const { data } = await apiClient.get<Order>(`/orders/${id}`)
  return data
}

export interface OrderInput {
  customer_id: number
  items: { product_id: number; quantity: number }[]
  priority?: OrderPriority
  requested_delivery_date?: string
  notes?: string
}

export async function createOrder(input: OrderInput): Promise<Order> {
  const { data } = await apiClient.post<Order>('/orders', input)
  return data
}

export type OrderAction = 'confirm' | 'cancel' | 'hold' | 'release' | 'reserve'

/** Status changes; cancel and hold need a reason. */
export async function orderAction(
  id: number,
  action: OrderAction,
  reason?: string,
): Promise<Order> {
  const body = action === 'cancel' || action === 'hold' ? { reason } : undefined
  const { data } = await apiClient.post<Order>(`/orders/${id}/${action}`, body)
  return data
}

export async function allocateOrder(id: number): Promise<unknown[]> {
  const { data } = await apiClient.post<unknown[]>(`/orders/${id}/allocate`)
  return data
}

export async function getOrderShipment(id: number): Promise<Shipment | null> {
  const { data } = await apiClient.get<Shipment | null>(`/orders/${id}/shipment`)
  return data
}

export async function listOrderReturns(orderId: number): Promise<OrderReturn[]> {
  const { data } = await apiClient.get<Page<OrderReturn>>('/returns', {
    params: { order_id: orderId, limit: 50 },
  })
  return data.items
}

export async function listCustomers(q = ''): Promise<Page<Customer>> {
  const { data } = await apiClient.get<Page<Customer>>('/customers', {
    params: { q: q || undefined, is_active: true, limit: 20 },
  })
  return data
}

export async function getMyCustomer(): Promise<Customer> {
  const { data } = await apiClient.get<Customer>('/customers/me')
  return data
}
