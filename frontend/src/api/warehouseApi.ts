import type {
  BinDetail,
  GenerateLayoutInput,
  GenerateLayoutResult,
  Rack,
  Warehouse,
  WarehouseLayout,
  Zone,
  ZoneType,
} from '../types/warehouse'
import { apiClient } from './apiClient'

export const warehouseKeys = {
  all: ['warehouses'] as const,
  layout: (id: number, includeInactive: boolean) =>
    ['warehouses', id, 'layout', { includeInactive }] as const,
  bin: (code: string) => ['bins', 'by-code', code] as const,
}

export async function listWarehouses(): Promise<Warehouse[]> {
  const { data } = await apiClient.get<Warehouse[]>('/warehouses')
  return data
}

export async function getLayout(id: number, includeInactive = false): Promise<WarehouseLayout> {
  const { data } = await apiClient.get<WarehouseLayout>(`/warehouses/${id}/layout`, {
    params: includeInactive ? { include_inactive: true } : {},
  })
  return data
}

export async function createWarehouse(input: {
  code: string
  name: string
  address: string | null
}): Promise<Warehouse> {
  const { data } = await apiClient.post<Warehouse>('/warehouses', input)
  return data
}

export async function createZone(
  warehouseId: number,
  input: { code: string; name: string; zone_type: ZoneType },
): Promise<Zone> {
  const { data } = await apiClient.post<Zone>(`/warehouses/${warehouseId}/zones`, input)
  return data
}

export async function setZoneActive(zoneId: number, isActive: boolean): Promise<Zone> {
  const { data } = await apiClient.patch<Zone>(`/zones/${zoneId}`, { is_active: isActive })
  return data
}

export async function setRackActive(rackId: number, isActive: boolean): Promise<Rack> {
  const { data } = await apiClient.patch<Rack>(`/racks/${rackId}`, { is_active: isActive })
  return data
}

export async function generateLayout(
  zoneId: number,
  input: GenerateLayoutInput,
): Promise<GenerateLayoutResult> {
  const { data } = await apiClient.post<GenerateLayoutResult>(`/zones/${zoneId}/generate`, input)
  return data
}

/** Look up a bin by its location code (simulated barcode scan). */
export async function getBinByCode(locationCode: string): Promise<BinDetail> {
  const { data } = await apiClient.get<BinDetail>(
    `/bins/by-code/${encodeURIComponent(locationCode.trim())}`,
  )
  return data
}
