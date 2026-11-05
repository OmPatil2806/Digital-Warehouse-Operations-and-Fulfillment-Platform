import { makeProduct, page } from './catalogFixtures'
import type { BinDetail, FitResult } from '../types/warehouse'

export const MOUSE = makeProduct({ id: 8, sku: 'ACC-MOU1', name: 'Wireless Mouse' })

export function makeBinDetail(code = 'WH01-ZA-R08-S04-B06', id = 30): BinDetail {
  const [wh, zone] = code.split('-')
  return {
    id,
    shelf_id: 1,
    code: code.split('-')[4],
    location_code: code,
    max_weight_kg: '30.000',
    max_volume_cm3: 120000,
    is_active: true,
    created_at: '',
    updated_at: '',
    warehouse: {
      id: wh === 'WH01' ? 1 : 2,
      code: wh,
      name: 'Main',
      address: null,
      is_active: true,
      created_at: '',
      updated_at: '',
    },
    zone: {
      id: 1,
      warehouse_id: 1,
      code: zone,
      name: 'Picking A',
      zone_type: 'picking',
      is_active: true,
      created_at: '',
      updated_at: '',
    },
    rack: {
      id: 1,
      zone_id: 1,
      code: 'R08',
      distance_to_packing_m: '18.0',
      is_active: true,
      created_at: '',
      updated_at: '',
    },
    shelf: {
      id: 1,
      rack_id: 1,
      code: 'S04',
      level: 4,
      is_active: true,
      created_at: '',
      updated_at: '',
    },
  } as BinDetail
}

export function makeFit(overrides: Partial<FitResult> = {}): FitResult {
  return {
    fits: true,
    reasons: [],
    required_weight_kg: '1.800',
    required_volume_cm3: '5720.000',
    max_weight_kg: '30.000',
    max_volume_cm3: 120000,
    used_weight_kg: '0',
    used_volume_cm3: '0',
    ...overrides,
  }
}

export const productPage = page([MOUSE])
