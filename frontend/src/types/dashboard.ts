/** Responses of /dashboards/*. Decimals arrive as exact strings; money is null for staff. */

export interface Period {
  date_from: string
  date_to: string
  days: number
}

export interface DateRangeParams {
  date_from?: string
  date_to?: string
}

export interface RateKpi {
  good: number
  total: number
  percent: string | null
}

export interface DurationKpi {
  orders: number
  average_hours: string | null
  median_hours: string | null
}

// ------------------------------------------------------------------- overview
export interface OverviewDashboard {
  period: Period
  include_financials: boolean
  inventory: {
    value_at_cost: string | null
    units_on_hand: number
    units_available: number
    units_reserved: number
    units_damaged: number
    low_stock_products: number
    out_of_stock_products: number
  }
  orders: {
    open: number
    backordered: number
    on_hold: number
    placed_in_period: number
    shipped_in_period: number
    delivered_in_period: number
    shipped_today: number
  }
  shipments: { on_the_way: number; delayed: number }
  alerts: { unresolved: number; critical: number }
  purchasing: { open: number; overdue: number; open_value: string | null }
}

// ------------------------------------------------------------------ inventory
export type StockStatus = 'ok' | 'low' | 'out'

export interface ProductStockKpi {
  product_id: number
  sku: string
  name: string
  category: string
  status: StockStatus
  min_stock: number
  units_on_hand: number
  units_available: number
  units_picked: number
  avg_daily_demand: string
  days_of_supply: string | null
  turnover: string | null
  value_at_cost: string | null
}

export interface InventoryDashboard {
  period: Period
  include_financials: boolean
  totals: {
    value_at_cost: string | null
    value_at_price: string | null
    units_on_hand: number
    units_available: number
    units_reserved: number
    units_damaged: number
    units_picked: number
  }
  turnover: string | null
  days_of_supply: string | null
  stock_status: Record<StockStatus, number>
  by_category: {
    category_id: number
    category: string
    products: number
    units_on_hand: number
    value_at_cost: string | null
    value_at_price: string | null
  }[]
  products: ProductStockKpi[]
  products_total: number
}

// ---------------------------------------------------------------- fulfillment
export interface FulfillmentDashboard {
  period: Period
  totals: { placed: number; shipped: number; delivered: number; cancelled: number }
  per_day: { day: string; placed: number; shipped: number; delivered: number }[]
  fulfillment_time: DurationKpi
  cycle_time: DurationKpi
  on_time_delivery: RateKpi
  picking_accuracy: RateKpi
  by_status: { status: string; count: number }[]
}

// ------------------------------------------------------------------ warehouse
export interface SpaceUse {
  bins: number
  occupied_bins: number
  occupancy_percent: string | null
  max_weight_kg: string
  used_weight_kg: string
  weight_percent: string | null
  max_volume_cm3: number
  used_volume_cm3: string
  volume_percent: string | null
}

export interface ZoneUse extends SpaceUse {
  zone_id: number
  warehouse: string
  code: string
  name: string
  zone_type: string
  is_active: boolean
  picks: number
  units_picked: number
}

export interface WarehouseDashboard {
  period: Period
  total: SpaceUse
  zones: ZoneUse[]
}

// ------------------------------------------------------------------ suppliers
export interface SupplierSummary {
  received_orders: number
  lead_time_avg_days: string | null
  lead_time_variance: string | null
  lead_time_stddev_days: string | null
  on_time: RateKpi
  open_orders: number
  overdue_orders: number
  open_value: string | null
}

export interface SupplierKpi extends SupplierSummary {
  supplier_id: number
  code: string
  name: string
  is_active: boolean
  promised_lead_time_days: number
  reliability_score: string
}

export interface SupplierDashboard extends SupplierSummary {
  period: Period
  include_financials: boolean
  suppliers: SupplierKpi[]
}
