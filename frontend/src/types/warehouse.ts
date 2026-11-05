/** Types mirroring the backend warehouse-layout schemas. Decimals arrive as strings. */

export const ZONE_TYPES = ['picking', 'bulk', 'cold', 'hazardous', 'returns'] as const
export type ZoneType = (typeof ZONE_TYPES)[number]

export interface Warehouse {
  id: number
  code: string
  name: string
  address: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Zone {
  id: number
  warehouse_id: number
  code: string
  name: string
  zone_type: ZoneType
  is_active: boolean
}

export interface Rack {
  id: number
  zone_id: number
  code: string
  distance_to_packing_m: string
  is_active: boolean
}

export interface Shelf {
  id: number
  rack_id: number
  code: string
  level: number
  is_active: boolean
}

export interface Bin {
  id: number
  shelf_id: number
  code: string
  location_code: string
  max_weight_kg: string
  max_volume_cm3: number
  is_active: boolean
}

export interface BinDetail extends Bin {
  warehouse: Warehouse
  zone: Zone
  rack: Rack
  shelf: Shelf
}

export interface CapacityTotals {
  bins: number
  active_bins: number
  max_weight_kg: string
  max_volume_cm3: number
}

export interface LayoutShelf extends Shelf {
  bins: Bin[]
}

export interface LayoutRack extends Rack {
  shelves: LayoutShelf[]
}

export interface LayoutZone extends Zone {
  totals: CapacityTotals
  racks: LayoutRack[]
}

export interface WarehouseLayout extends Warehouse {
  totals: CapacityTotals
  zones: LayoutZone[]
}

export interface GenerateLayoutInput {
  racks: number
  shelves_per_rack: number
  bins_per_shelf: number
  max_weight_kg: string
  max_volume_cm3: number
  first_rack_distance_m: string
  distance_step_m: string
}

export interface GenerateLayoutResult {
  racks_created: number
  shelves_created: number
  bins_created: number
  first_location_code: string
  last_location_code: string
}

/** GET /bins/{id}/fit: would `quantity` more units fit on top of the bin's contents? */
export interface FitResult {
  fits: boolean
  reasons: string[]
  required_weight_kg: string
  required_volume_cm3: string
  max_weight_kg: string
  max_volume_cm3: number
  used_weight_kg: string
  used_volume_cm3: string
}
