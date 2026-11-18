/** Responses of /ml/* (backend app/schemas/ml.py). Predictions come from the latest
 * scoring run; numbers are plain JSON numbers. */

import type { Page } from './catalog'

export type DecisionStatus = 'pending' | 'approved' | 'rejected'
export type RiskLevel = 'low' | 'medium' | 'high'
export type MovementClass = 'fast' | 'medium' | 'slow'

export interface ProductRef {
  id: number
  sku: string
  name: string
}

export interface ScoringInfo {
  model_name: string
  is_baseline: boolean
  scored_at: string
  as_of: string
}

export interface ModelSummary {
  use_case: string
  model_name: string
  version: string
  is_baseline: boolean
  dataset_version: string
  trained_at: string
  test_metrics: Record<string, number>
  scored_at: string | null
  as_of: string | null
  predictions: number
}

export interface ForecastDay {
  day: string
  expected_units: number
  low_units: number
  high_units: number
}

export interface ForecastTotal {
  days: number
  expected_units: number
  low_units: number
  high_units: number
}

export interface DemandForecast {
  product: ProductRef
  scoring: ScoringInfo | null
  days: ForecastDay[]
  totals: ForecastTotal[]
}

export interface Decision {
  status: DecisionStatus
  decided_by_id: number | null
  decided_at: string | null
  decision_note: string | null
}

export interface ReorderRecommendation extends Decision {
  id: number
  product: ProductRef
  warehouse_id: number
  warehouse_code: string
  probability: number
  priority: RiskLevel
  reorder_date: string
  quantity: number
  reasons: string[]
  purchase_order_id: number | null
  scored_at: string
  as_of: string
}

export interface MovementInfo {
  product: ProductRef
  movement_class: MovementClass
  picks_per_day: number
  scored_at: string
  as_of: string
}

export interface MovementSummary {
  scoring: ScoringInfo | null
  counts: Record<MovementClass, number>
  pick_share: Record<MovementClass, number>
}

export interface BinRef {
  id: number
  location_code: string
  zone_type: string
  level: number
  distance_to_packing_m: number
}

export interface SlottingRecommendation extends Decision {
  id: number
  product: ProductRef
  warehouse_id: number
  warehouse_code: string
  current_bin: BinRef | null
  recommended_bin: BinRef
  current_seconds_per_day: number | null
  recommended_seconds_per_day: number
  seconds_saved_per_day: number | null
  scored_at: string
  as_of: string
}

export interface DelayRisk {
  order_id: number
  order_number: string
  shipment_id: number
  probability: number
  risk_level: RiskLevel
  reasons: string[]
  scored_at: string
  as_of: string
}

export interface OrderDelayRisk {
  order_id: number
  prediction: DelayRisk | null
}

export interface RecommendedProduct {
  rank: number
  product: ProductRef
  score: number
}

export interface ProductRecommendations {
  product: ProductRef
  scoring: ScoringInfo | null
  items: RecommendedProduct[]
}

export type ReorderPage = Page<ReorderRecommendation>
export type SlottingPage = Page<SlottingRecommendation>
export type MovementPage = Page<MovementInfo>
export type DelayRiskPage = Page<DelayRisk>

export interface ListParams {
  offset?: number
  limit?: number
}
