import type {
  FulfillmentDashboard,
  InventoryDashboard,
  SupplierDashboard,
  WarehouseDashboard,
} from '../../types/dashboard'
import type { CsvTable } from '../../utils/csv'

/**
 * What each report tab exports: its detail table with raw values (plain numbers and
 * ISO dates, no currency signs or units) so spreadsheets can calculate with them.
 * Money columns are only included for users who may see them.
 */

export function inventoryCsv(d: InventoryDashboard, financials: boolean): CsvTable {
  return {
    columns: [
      'sku',
      'name',
      'category',
      'status',
      'min_stock',
      'units_on_hand',
      'units_available',
      'units_picked',
      'avg_daily_demand',
      'days_of_supply',
      'turnover',
      ...(financials ? ['value_at_cost_eur'] : []),
    ],
    rows: d.products.map((p) => [
      p.sku,
      p.name,
      p.category,
      p.status,
      p.min_stock,
      p.units_on_hand,
      p.units_available,
      p.units_picked,
      p.avg_daily_demand,
      p.days_of_supply,
      p.turnover,
      ...(financials ? [p.value_at_cost] : []),
    ]),
  }
}

export function fulfillmentCsv(d: FulfillmentDashboard): CsvTable {
  return {
    columns: ['day', 'placed', 'shipped', 'delivered'],
    rows: d.per_day.map((day) => [day.day, day.placed, day.shipped, day.delivered]),
  }
}

export function warehouseCsv(d: WarehouseDashboard): CsvTable {
  return {
    columns: [
      'warehouse',
      'zone',
      'name',
      'zone_type',
      'is_active',
      'bins',
      'occupied_bins',
      'occupancy_percent',
      'max_weight_kg',
      'used_weight_kg',
      'weight_percent',
      'max_volume_cm3',
      'used_volume_cm3',
      'volume_percent',
      'picks',
      'units_picked',
    ],
    rows: d.zones.map((z) => [
      z.warehouse,
      z.code,
      z.name,
      z.zone_type,
      z.is_active,
      z.bins,
      z.occupied_bins,
      z.occupancy_percent,
      z.max_weight_kg,
      z.used_weight_kg,
      z.weight_percent,
      z.max_volume_cm3,
      z.used_volume_cm3,
      z.volume_percent,
      z.picks,
      z.units_picked,
    ]),
  }
}

export function supplierCsv(d: SupplierDashboard, financials: boolean): CsvTable {
  return {
    columns: [
      'code',
      'name',
      'is_active',
      'promised_lead_time_days',
      'received_orders',
      'lead_time_avg_days',
      'lead_time_variance',
      'lead_time_stddev_days',
      'on_time',
      'on_time_total',
      'on_time_percent',
      'open_orders',
      'overdue_orders',
      ...(financials ? ['open_value_eur'] : []),
    ],
    rows: d.suppliers.map((s) => [
      s.code,
      s.name,
      s.is_active,
      s.promised_lead_time_days,
      s.received_orders,
      s.lead_time_avg_days,
      s.lead_time_variance,
      s.lead_time_stddev_days,
      s.on_time.good,
      s.on_time.total,
      s.on_time.percent,
      s.open_orders,
      s.overdue_orders,
      ...(financials ? [s.open_value] : []),
    ]),
  }
}
