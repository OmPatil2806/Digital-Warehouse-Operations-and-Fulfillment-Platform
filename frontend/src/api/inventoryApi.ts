import type { Page } from '../types/catalog'
import type { InventoryRow, Movement, MovementType, ProductStock } from '../types/inventory'
import { apiClient } from './apiClient'

export const inventoryKeys = {
  all: ['inventory'] as const,
  stock: (params: object) => ['inventory', 'stock', params] as const,
  product: (productId: number) => ['inventory', 'product', productId] as const,
  movements: (params: object) => ['inventory', 'movements', params] as const,
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
