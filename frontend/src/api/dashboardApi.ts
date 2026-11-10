import type {
  DateRangeParams,
  FulfillmentDashboard,
  InventoryDashboard,
  OverviewDashboard,
  SupplierDashboard,
  WarehouseDashboard,
} from '../types/dashboard'
import { apiClient } from './apiClient'

export const dashboardKeys = {
  all: ['dashboards'] as const,
  view: (name: string, range: DateRangeParams) => ['dashboards', name, range] as const,
}

/** Empty dates are left out, so the API uses its default (the last 30 days). */
function rangeParams(range: DateRangeParams): DateRangeParams {
  return {
    date_from: range.date_from || undefined,
    date_to: range.date_to || undefined,
  }
}

async function get<T>(path: string, params: object): Promise<T> {
  const { data } = await apiClient.get<T>(`/dashboards/${path}`, { params })
  return data
}

export const getOverviewDashboard = (range: DateRangeParams = {}) =>
  get<OverviewDashboard>('overview', rangeParams(range))

export const getInventoryDashboard = (range: DateRangeParams = {}, limit?: number) =>
  get<InventoryDashboard>('inventory', { ...rangeParams(range), limit })

export const getFulfillmentDashboard = (range: DateRangeParams = {}) =>
  get<FulfillmentDashboard>('fulfillment', rangeParams(range))

export const getWarehouseDashboard = (range: DateRangeParams = {}) =>
  get<WarehouseDashboard>('warehouse', rangeParams(range))

export const getSupplierDashboard = (range: DateRangeParams = {}) =>
  get<SupplierDashboard>('suppliers', rangeParams(range))
