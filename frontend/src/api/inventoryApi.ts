import type { Page } from '../types/catalog'
import type {
  AdjustmentKind,
  AdjustmentSubmitResult,
  ApprovalQueue,
  CycleCount,
  CycleCountStatus,
  CycleCountSummary,
  DocumentStatus,
  InventoryRow,
  Movement,
  MovementType,
  ProductStock,
  StockAdjustment,
  StockTransfer,
  TransferSubmitResult,
} from '../types/inventory'
import { apiClient } from './apiClient'

export const inventoryKeys = {
  all: ['inventory'] as const,
  stock: (params: object) => ['inventory', 'stock', params] as const,
  product: (productId: number) => ['inventory', 'product', productId] as const,
  movements: (params: object) => ['inventory', 'movements', params] as const,
  requests: ['inventory', 'requests'] as const,
  cycleCounts: ['inventory', 'cycle-counts'] as const,
  cycleCount: (id: number) => ['inventory', 'cycle-counts', id] as const,
}

export interface InventoryListParams {
  q?: string
  productId?: number
  binId?: number
  warehouseId?: number
  zoneId?: number
  includeEmpty?: boolean
  offset?: number
  limit?: number
}

export async function listInventory(params: InventoryListParams = {}): Promise<Page<InventoryRow>> {
  const { data } = await apiClient.get<Page<InventoryRow>>('/inventory', {
    params: {
      q: params.q || undefined,
      product_id: params.productId,
      bin_id: params.binId,
      warehouse_id: params.warehouseId,
      zone_id: params.zoneId,
      include_empty: params.includeEmpty || undefined,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}

export async function getProductStock(productId: number): Promise<ProductStock> {
  const { data } = await apiClient.get<ProductStock>(`/inventory/products/${productId}`)
  return data
}

export interface MovementListParams {
  productId?: number
  binId?: number
  movementType?: MovementType
  offset?: number
  limit?: number
}

export async function listMovements(params: MovementListParams = {}): Promise<Page<Movement>> {
  const { data } = await apiClient.get<Page<Movement>>('/inventory/movements', {
    params: {
      product_id: params.productId,
      bin_id: params.binId,
      movement_type: params.movementType,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}

// ------------------------------------------------------------------ operations
export async function receiveStock(input: {
  product_id: number
  bin_id: number
  quantity: number
  reason?: string
}): Promise<InventoryRow> {
  const { data } = await apiClient.post<InventoryRow>('/inventory/receive', input)
  return data
}

export async function submitAdjustment(input: {
  product_id: number
  bin_id: number
  kind: AdjustmentKind
  quantity: number
  reason: string
}): Promise<AdjustmentSubmitResult> {
  const { data } = await apiClient.post<AdjustmentSubmitResult>('/inventory/adjustments', input)
  return data
}

export async function submitTransfer(input: {
  product_id: number
  from_bin_id: number
  to_bin_id: number
  quantity: number
  reason?: string
}): Promise<TransferSubmitResult> {
  const { data } = await apiClient.post<TransferSubmitResult>('/inventory/transfers', input)
  return data
}

// -------------------------------------------------------------------- requests
export type RequestKind = 'adjustments' | 'transfers'

export async function getApprovalQueue(): Promise<ApprovalQueue> {
  const { data } = await apiClient.get<ApprovalQueue>('/inventory/approvals')
  return data
}

export async function listMyRequests(): Promise<{
  adjustments: StockAdjustment[]
  transfers: StockTransfer[]
}> {
  const params = { mine: true, limit: 25 }
  const [adjustments, transfers] = await Promise.all([
    apiClient.get<Page<StockAdjustment>>('/inventory/adjustments', { params }),
    apiClient.get<Page<StockTransfer>>('/inventory/transfers', { params }),
  ])
  return { adjustments: adjustments.data.items, transfers: transfers.data.items }
}

/** Approve (note optional), reject (note required) or cancel (own request) a request. */
export async function decideRequest(
  kind: RequestKind,
  id: number,
  action: 'approve' | 'reject' | 'cancel',
  note?: string,
): Promise<{ id: number; status: DocumentStatus }> {
  const body = action === 'cancel' ? undefined : { note: note || undefined }
  const { data } = await apiClient.post<{ id: number; status: DocumentStatus }>(
    `/inventory/${kind}/${id}/${action}`,
    body,
  )
  return data
}

// ---------------------------------------------------------------- cycle counts
export async function listCycleCounts(
  params: { status?: CycleCountStatus; offset?: number; limit?: number } = {},
): Promise<Page<CycleCountSummary>> {
  const { data } = await apiClient.get<Page<CycleCountSummary>>('/cycle-counts', { params })
  return data
}

export async function startCycleCount(input: {
  bin_id: number
  note?: string
}): Promise<CycleCount> {
  const { data } = await apiClient.post<CycleCount>('/cycle-counts', input)
  return data
}

export async function getCycleCount(id: number): Promise<CycleCount> {
  const { data } = await apiClient.get<CycleCount>(`/cycle-counts/${id}`)
  return data
}

export async function recordCounts(
  id: number,
  lines: { product_id: number; counted_quantity: number }[],
): Promise<CycleCount> {
  const { data } = await apiClient.put<CycleCount>(`/cycle-counts/${id}/lines`, { lines })
  return data
}

export async function cycleCountAction(
  id: number,
  action: 'submit' | 'approve' | 'reject' | 'cancel',
  note?: string,
): Promise<CycleCount> {
  const body = action === 'approve' || action === 'reject' ? { note: note || undefined } : undefined
  const { data } = await apiClient.post<CycleCount>(`/cycle-counts/${id}/${action}`, body)
  return data
}
