import type {
  DemandForecast,
  MovementSummary,
  ProductRecommendations,
  ReorderRecommendation,
  SlottingRecommendation,
} from '../types/ml'

const scoring = {
  model_name: 'lstm',
  is_baseline: false,
  scored_at: '2026-11-10T12:00:00Z',
  as_of: '2026-11-10',
}
const product = { id: 7, sku: 'ELE-00007', name: 'Monitor 27"' }
const pending = {
  status: 'pending',
  decided_by_id: null,
  decided_at: null,
  decision_note: null,
} as const

export const forecastFixture: DemandForecast = {
  product,
  scoring,
  days: [
    { day: '2026-11-11', expected_units: 2.4, low_units: 0.5, high_units: 5 },
    { day: '2026-11-12', expected_units: 12.6, low_units: 4, high_units: 20 },
  ],
  totals: [{ days: 7, expected_units: 38.2, low_units: 10, high_units: 70 }],
}

export function reorderFixture(
  overrides: Partial<ReorderRecommendation> = {},
): ReorderRecommendation {
  return {
    id: 11,
    product,
    warehouse_id: 1,
    warehouse_code: 'WH01',
    probability: 0.82,
    priority: 'high',
    reorder_date: '2026-11-10',
    quantity: 63,
    reasons: ['Low available stock', 'Seasonal peak ahead'],
    purchase_order_id: null,
    scored_at: scoring.scored_at,
    as_of: scoring.as_of,
    ...pending,
    ...overrides,
  }
}

export function slottingFixture(
  overrides: Partial<SlottingRecommendation> = {},
): SlottingRecommendation {
  return {
    id: 21,
    product,
    warehouse_id: 1,
    warehouse_code: 'WH01',
    current_bin: {
      id: 5,
      location_code: 'WH01-ZB-R09-S04-B02',
      zone_type: 'bulk',
      level: 4,
      distance_to_packing_m: 95.5,
    },
    recommended_bin: {
      id: 1,
      location_code: 'WH01-ZA-R01-S01-B01',
      zone_type: 'picking',
      level: 1,
      distance_to_packing_m: 6.3,
    },
    current_seconds_per_day: 900,
    recommended_seconds_per_day: 300,
    seconds_saved_per_day: 600,
    scored_at: scoring.scored_at,
    as_of: scoring.as_of,
    ...pending,
    ...overrides,
  }
}

export const movementSummaryFixture: MovementSummary = {
  scoring: { ...scoring, model_name: 'abc', is_baseline: true },
  counts: { fast: 2, medium: 3, slow: 5 },
  pick_share: { fast: 0.8, medium: 0.15, slow: 0.05 },
}

export const recommendationsFixture: ProductRecommendations = {
  product,
  scoring: { ...scoring, model_name: 'frequently_bought_together', is_baseline: true },
  items: [
    { rank: 1, product: { id: 8, sku: 'ACC-00008', name: 'Wireless Mouse' }, score: 9 },
    { rank: 2, product: { id: 9, sku: 'ACC-00009', name: 'USB-C Hub' }, score: 7 },
  ],
}
