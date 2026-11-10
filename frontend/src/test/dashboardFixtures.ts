import type {
  FulfillmentDashboard,
  InventoryDashboard,
  OverviewDashboard,
  SpaceUse,
  SupplierDashboard,
  SupplierKpi,
  WarehouseDashboard,
} from '../types/dashboard'

const PERIOD = { date_from: '2026-10-12', date_to: '2026-11-10', days: 30 }

export function makeOverview(overrides: Partial<OverviewDashboard> = {}): OverviewDashboard {
  return {
    period: PERIOD,
    include_financials: true,
    inventory: {
      value_at_cost: '70552.10',
      units_on_hand: 4036,
      units_available: 4026,
      units_reserved: 10,
      units_damaged: 0,
      low_stock_products: 6,
      out_of_stock_products: 1,
    },
    orders: {
      open: 4,
      backordered: 1,
      on_hold: 0,
      placed_in_period: 7,
      shipped_in_period: 3,
      delivered_in_period: 1,
      shipped_today: 2,
    },
    shipments: { on_the_way: 2, delayed: 1 },
    alerts: { unresolved: 8, critical: 1 },
    purchasing: { open: 2, overdue: 1, open_value: '1812.00' },
    ...overrides,
  }
}

export function makeFulfillment(
  overrides: Partial<FulfillmentDashboard> = {},
): FulfillmentDashboard {
  return {
    period: PERIOD,
    totals: { placed: 7, shipped: 3, delivered: 1, cancelled: 0 },
    per_day: [
      { day: '2026-11-08', placed: 2, shipped: 1, delivered: 0 },
      { day: '2026-11-09', placed: 0, shipped: 0, delivered: 0 },
      { day: '2026-11-10', placed: 5, shipped: 2, delivered: 1 },
    ],
    fulfillment_time: { orders: 3, average_hours: '22.0', median_hours: '12.0' },
    cycle_time: { orders: 1, average_hours: '98.0', median_hours: '98.0' },
    on_time_delivery: { good: 3, total: 4, percent: '75.0' },
    picking_accuracy: { good: 5, total: 5, percent: '100.0' },
    by_status: [
      { status: 'created', count: 1 },
      { status: 'confirmed', count: 0 },
      { status: 'shipped', count: 2 },
    ],
    ...overrides,
  }
}

export function makeInventory(overrides: Partial<InventoryDashboard> = {}): InventoryDashboard {
  return {
    period: PERIOD,
    include_financials: true,
    totals: {
      value_at_cost: '70552.10',
      value_at_price: '128380.79',
      units_on_hand: 4036,
      units_available: 4026,
      units_reserved: 10,
      units_damaged: 0,
      units_picked: 20,
    },
    turnover: '0.01',
    days_of_supply: '1520.5',
    stock_status: { ok: 44, low: 5, out: 1 },
    by_category: [
      {
        category_id: 1,
        category: 'Laptops',
        products: 4,
        units_on_hand: 20,
        value_at_cost: '28960.00',
        value_at_price: '38000.00',
      },
      {
        category_id: 2,
        category: 'Tools',
        products: 6,
        units_on_hand: 90,
        value_at_cost: '2790.00',
        value_at_price: '5310.00',
      },
    ],
    products: [
      {
        product_id: 9,
        sku: 'TOO-LAD1',
        name: 'Aluminium Step Ladder',
        category: 'Tools',
        status: 'out',
        min_stock: 3,
        units_on_hand: 0,
        units_available: 0,
        units_picked: 1,
        avg_daily_demand: '0.03',
        days_of_supply: '0.0',
        turnover: null,
        value_at_cost: '0.00',
      },
      {
        product_id: 4,
        sku: 'HOM-KET1',
        name: 'Electric Kettle',
        category: 'Home',
        status: 'ok',
        min_stock: 5,
        units_on_hand: 37,
        units_available: 37,
        units_picked: 3,
        avg_daily_demand: '0.10',
        days_of_supply: '370.0',
        turnover: '0.16',
        value_at_cost: '555.00',
      },
      {
        product_id: 5,
        sku: 'ACC-HDS1',
        name: 'Headset',
        category: 'Accessories',
        status: 'low',
        min_stock: 10,
        units_on_hand: 6,
        units_available: 6,
        units_picked: 0,
        avg_daily_demand: '0.00',
        days_of_supply: null,
        turnover: '0.00',
        value_at_cost: '468.00',
      },
    ],
    products_total: 50,
    ...overrides,
  }
}

function space(overrides: Partial<SpaceUse> = {}): SpaceUse {
  return {
    bins: 192,
    occupied_bins: 50,
    occupancy_percent: '26.0',
    max_weight_kg: '19200.000',
    used_weight_kg: '2860.800',
    weight_percent: '14.9',
    max_volume_cm3: 38_400_000,
    used_volume_cm3: '5337600',
    volume_percent: '13.9',
    ...overrides,
  }
}

export function makeWarehouse(overrides: Partial<WarehouseDashboard> = {}): WarehouseDashboard {
  const zone = (id: number, code: string, name: string, zone_type: string, extra = {}) => ({
    ...space(),
    zone_id: id,
    warehouse: 'WH01',
    code,
    name,
    zone_type,
    is_active: true,
    picks: 0,
    units_picked: 0,
    ...extra,
  })
  return {
    period: PERIOD,
    total: space({ bins: 274, occupied_bins: 84, occupancy_percent: '30.7' }),
    zones: [
      zone(1, 'ZA', 'Picking', 'picking', { picks: 4, units_picked: 10 }),
      zone(2, 'ZC', 'Cold storage', 'cold', { occupancy_percent: '62.5', weight_percent: '52.1' }),
      zone(3, 'ZX', 'Empty zone', 'bulk', {
        ...space({ bins: 0, occupied_bins: 0, occupancy_percent: null, weight_percent: null }),
      }),
    ],
    ...overrides,
  }
}

function supplier(overrides: Partial<SupplierKpi> = {}): SupplierKpi {
  return {
    supplier_id: 1,
    code: 'SUP-001',
    name: 'Nordtech Distribution GmbH',
    is_active: true,
    promised_lead_time_days: 5,
    reliability_score: '0.97',
    received_orders: 2,
    lead_time_avg_days: '7.8',
    lead_time_variance: '7.56',
    lead_time_stddev_days: '2.8',
    on_time: { good: 1, total: 2, percent: '50.0' },
    open_orders: 0,
    overdue_orders: 0,
    open_value: '0.00',
    ...overrides,
  }
}

export function makeSuppliers(overrides: Partial<SupplierDashboard> = {}): SupplierDashboard {
  return {
    period: PERIOD,
    include_financials: true,
    received_orders: 2,
    lead_time_avg_days: '7.8',
    lead_time_variance: '7.56',
    lead_time_stddev_days: '2.8',
    on_time: { good: 1, total: 2, percent: '50.0' },
    open_orders: 2,
    overdue_orders: 1,
    open_value: '1812.00',
    suppliers: [
      supplier(),
      supplier({
        supplier_id: 4,
        code: 'SUP-004',
        name: 'AutoParts Europa SpA',
        promised_lead_time_days: 9,
        received_orders: 0,
        lead_time_avg_days: null,
        lead_time_variance: null,
        lead_time_stddev_days: null,
        on_time: { good: 0, total: 0, percent: null },
        open_orders: 1,
        overdue_orders: 1,
        open_value: '1440.00',
      }),
    ],
    ...overrides,
  }
}
