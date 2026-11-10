import { BrainCircuit, ShoppingCart } from 'lucide-react'
import { Link } from 'react-router'

import { alertKeys, listAlerts } from '../../api/alertsApi'
import {
  dashboardKeys,
  getFulfillmentDashboard,
  getInventoryDashboard,
  getOverviewDashboard,
} from '../../api/dashboardApi'
import {
  fulfillmentKeys,
  listPackingTasks,
  listPickingTasks,
  listShipments,
  shipmentKeys,
} from '../../api/fulfillmentApi'
import { listOrders, orderKeys } from '../../api/ordersApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import { useUrlState } from '../../hooks/useUrlState'
import type { ProductStockKpi } from '../../types/dashboard'
import {
  formatDays,
  formatInteger,
  formatMoney,
  formatPercentage,
  plural,
} from '../../utils/format'
import { Badge } from '../common/Badge'
import { formatDate, STATUS_LABELS, STATUS_TONES } from '../orders/orderFormat'
import { SHIPMENT_TONES } from '../shipments/shipmentFormat'
import { DateRangePicker } from './DateRangePicker'
import { DEFAULT_RANGE, rangeParams, type DateRangeValue } from './dateRange'
import { STOCK_STATUS } from './dashboardFormat'
import { KpiCard } from './KpiCard'
import { OrdersTrendChart } from './OrdersTrendChart'
import { RecentAlerts } from './RecentAlerts'
import { StockStatusChart } from './StockStatusChart'

const URL_DEFAULTS = { range: DEFAULT_RANGE.preset as string, from: '', to: '' }
const ALERTS = { status: 'unresolved' as const, limit: 5 }

function useLatestAlerts() {
  return useApiQuery(alertKeys.list(ALERTS), () => listAlerts(ALERTS))
}

function periodWords(days: number | undefined): string {
  return days ? `in the last ${days} days` : 'in the period'
}

// ============================================================================ manager
/** Managers and admins: the state of the whole warehouse for a chosen period. */
export function ManagerOverview() {
  const [url, setUrl] = useUrlState(URL_DEFAULTS)
  const range: DateRangeValue = {
    preset: url.range as DateRangeValue['preset'],
    from: url.from,
    to: url.to,
  }
  const params = rangeParams(range)
  const options = { keepPrevious: true }
  const overview = useApiQuery(
    dashboardKeys.view('overview', params),
    () => getOverviewDashboard(params),
    options,
  )
  const fulfillment = useApiQuery(
    dashboardKeys.view('fulfillment', params),
    () => getFulfillmentDashboard(params),
    options,
  )
  const inventory = useApiQuery(
    dashboardKeys.view('inventory', params),
    () => getInventoryDashboard(params, 5),
    options,
  )
  const alerts = useLatestAlerts()

  const o = overview.data
  const f = fulfillment.data
  const days = o?.period.days
  const loadingTiles = overview.isPending || fulfillment.isPending

  return (
    <div className="space-y-6">
      <DateRangePicker
        value={range}
        onChange={(next) => setUrl({ range: next.preset, from: next.from, to: next.to })}
      />
      {(overview.errorMessage || fulfillment.errorMessage) && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {overview.errorMessage ?? fulfillment.errorMessage}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="Stock value"
          isLoading={loadingTiles}
          value={formatMoney(o?.inventory.value_at_cost)}
          detail={`${plural(o?.inventory.units_available, 'unit')} available, at purchase cost`}
        />
        <KpiCard
          label="Open orders"
          isLoading={loadingTiles}
          value={formatInteger(o?.orders.open)}
          status={
            o?.orders.backordered
              ? { tone: 'warning', label: `${o.orders.backordered} waiting for stock` }
              : undefined
          }
          detail={o?.orders.on_hold ? `${o.orders.on_hold} on hold` : 'Placed, not shipped yet'}
        />
        <KpiCard
          label="Orders shipped"
          isLoading={loadingTiles}
          value={formatInteger(o?.orders.shipped_in_period)}
          detail={`${periodWords(days)} · ${formatInteger(o?.orders.shipped_today)} today`}
        />
        <KpiCard
          label="On-time delivery"
          isLoading={loadingTiles}
          value={formatPercentage(f?.on_time_delivery.percent)}
          detail={
            f?.on_time_delivery.total
              ? `${f.on_time_delivery.good} of ${plural(f.on_time_delivery.total, 'delivery', 'deliveries')} ${periodWords(days)}`
              : `No deliveries ${periodWords(days)}`
          }
        />
        <KpiCard
          label="Open alerts"
          isLoading={loadingTiles}
          value={formatInteger(o?.alerts.unresolved)}
          status={
            o?.alerts.critical
              ? { tone: 'critical', label: `${o.alerts.critical} critical` }
              : { tone: 'good', label: 'None critical' }
          }
        />
        <KpiCard
          label="Purchase orders"
          isLoading={loadingTiles}
          value={formatInteger(o?.purchasing.open)}
          status={
            o?.purchasing.overdue
              ? { tone: 'serious', label: `${o.purchasing.overdue} overdue` }
              : undefined
          }
          detail={`Open · ${formatMoney(o?.purchasing.open_value)} still to arrive`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2">
          <OrdersTrendChart
            perDay={f?.per_day}
            isLoading={fulfillment.isPending}
            isRefreshing={fulfillment.isPlaceholderData}
            errorMessage={fulfillment.errorMessage}
          />
        </div>
        <StockStatusChart
          counts={inventory.data?.stock_status}
          isLoading={inventory.isPending}
          isRefreshing={inventory.isPlaceholderData}
          errorMessage={inventory.errorMessage}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <RunningOut
          products={inventory.data?.products}
          isLoading={inventory.isPending}
          errorMessage={inventory.errorMessage}
        />
        <RecentAlerts
          alerts={alerts.data?.items}
          total={alerts.data?.total}
          isLoading={alerts.isPending}
          errorMessage={alerts.errorMessage}
        />
      </div>

      <section
        aria-labelledby="ml-heading"
        className="flex items-start gap-3 rounded-xl border border-dashed border-slate-300 p-4"
      >
        <BrainCircuit size={20} className="mt-0.5 text-slate-400" aria-hidden="true" />
        <div>
          <h3 id="ml-heading" className="font-medium text-slate-700">
            ML insights
          </h3>
          <p className="text-sm text-slate-500">
            Forecast error, predicted stockouts and high-risk orders appear here once the models are
            trained (Phases 8 and 9).
          </p>
        </div>
      </section>
    </div>
  )
}

function RunningOut({
  products,
  isLoading,
  errorMessage,
}: {
  products: ProductStockKpi[] | undefined
  isLoading: boolean
  errorMessage: string | null
}) {
  return (
    <section
      aria-labelledby="running-out-heading"
      className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 id="running-out-heading" className="font-medium text-slate-900">
          Running out first
        </h3>
        <Link to="/inventory" className="text-xs font-medium text-blue-700 hover:underline">
          Inventory
        </Link>
      </div>
      {errorMessage ? (
        <p role="alert" className="text-sm text-red-700">
          {errorMessage}
        </p>
      ) : isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !products?.length ? (
        <p className="text-sm text-slate-500">No active products.</p>
      ) : (
        <table className="w-full table-fixed text-sm">
          <caption className="sr-only">Products with the fewest days of supply</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th scope="col" className="py-1.5 font-medium">
                Product
              </th>
              <th scope="col" className="w-20 py-1.5 text-right font-medium">
                Available
              </th>
              <th scope="col" className="w-24 py-1.5 text-right font-medium">
                Lasts
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums">
            {products.map((p) => (
              <tr key={p.product_id}>
                <th scope="row" className="py-1.5 pr-2 text-left font-normal break-words">
                  <span className="font-mono text-xs">{p.sku}</span>{' '}
                  <span className="text-slate-600">{p.name}</span>
                  {p.status !== 'ok' && (
                    <>
                      {' '}
                      <Badge tone={p.status === 'out' ? 'danger' : 'warning'}>
                        {STOCK_STATUS[p.status].label}
                      </Badge>
                    </>
                  )}
                </th>
                <td className="py-1.5 text-right">{formatInteger(p.units_available)}</td>
                <td className="py-1.5 text-right">
                  {p.days_of_supply === null ? 'no demand' : formatDays(p.days_of_supply)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// ============================================================================== staff
/** Staff: today's work on the floor. */
export function StaffOverview() {
  const overview = useApiQuery(dashboardKeys.view('overview', {}), () => getOverviewDashboard())
  const picking = useApiQuery(
    fulfillmentKeys.picking({ status: 'open', limit: 1 }),
    () => listPickingTasks({ status: 'open', limit: 1 }),
    { refetchInterval: 30_000 },
  )
  const packing = useApiQuery(fulfillmentKeys.packing('open'), () => listPackingTasks('open'), {
    refetchInterval: 30_000,
  })
  const alerts = useLatestAlerts()
  const o = overview.data

  return (
    <div className="space-y-6">
      {overview.errorMessage && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {overview.errorMessage}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="To pick"
          isLoading={picking.isPending}
          value={formatInteger(picking.data?.total)}
          detail={
            <Link className="text-blue-700 hover:underline" to="/fulfillment">
              Picking queue
            </Link>
          }
        />
        <KpiCard
          label="To pack"
          isLoading={packing.isPending}
          value={formatInteger(packing.data?.total)}
          detail={
            <Link className="text-blue-700 hover:underline" to="/fulfillment?view=packing">
              Packing station
            </Link>
          }
        />
        <KpiCard
          label="Shipped today"
          isLoading={overview.isPending}
          value={formatInteger(o?.orders.shipped_today)}
          detail={`${plural(o?.shipments.on_the_way, 'parcel')} on the way`}
        />
        <KpiCard
          label="Delayed shipments"
          isLoading={overview.isPending}
          value={formatInteger(o?.shipments.delayed)}
          status={
            o?.shipments.delayed
              ? { tone: 'serious', label: 'Needs follow-up' }
              : { tone: 'good', label: 'All on time' }
          }
        />
        <KpiCard
          label="Low stock"
          isLoading={overview.isPending}
          value={formatInteger(o?.inventory.low_stock_products)}
          detail={`${plural(o?.inventory.out_of_stock_products, 'product')} out of stock`}
        />
        <KpiCard
          label="Purchase orders to receive"
          isLoading={overview.isPending}
          value={formatInteger(o?.purchasing.open)}
          status={
            o?.purchasing.overdue
              ? { tone: 'serious', label: `${o.purchasing.overdue} overdue` }
              : undefined
          }
          detail={
            <Link className="text-blue-700 hover:underline" to="/purchase-orders">
              Purchase orders
            </Link>
          }
        />
      </div>
      <RecentAlerts
        alerts={alerts.data?.items}
        total={alerts.data?.total}
        isLoading={alerts.isPending}
        errorMessage={alerts.errorMessage}
      />
    </div>
  )
}

// =========================================================================== customer
/** Customers: their own recent orders and parcels. */
export function CustomerOverview() {
  const orders = useApiQuery(orderKeys.list({ limit: 5 }), () => listOrders({ limit: 5 }))
  const shipments = useApiQuery(shipmentKeys.list({ limit: 5 }), () => listShipments({ limit: 5 }))

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section
        aria-labelledby="my-orders-heading"
        className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      >
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h3 id="my-orders-heading" className="font-medium text-slate-900">
            My recent orders
          </h3>
          <Link
            to="/orders"
            className="flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline"
          >
            <ShoppingCart size={14} aria-hidden="true" />
            All orders and new order
          </Link>
        </div>
        {orders.errorMessage ? (
          <p role="alert" className="text-sm text-red-700">
            {orders.errorMessage}
          </p>
        ) : orders.isPending ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : !orders.data?.items.length ? (
          <p className="text-sm text-slate-500">You have not placed an order yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {orders.data.items.map((order) => (
              <li key={order.id} className="flex items-center justify-between gap-3 py-2">
                <div>
                  <Link
                    to={`/orders/${order.id}`}
                    className="font-mono text-xs font-medium text-blue-700 hover:underline"
                  >
                    {order.order_number}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {formatDate(order.created_at)} · {order.total_quantity} item(s) ·{' '}
                    {formatMoney(order.subtotal)}
                  </p>
                </div>
                <Badge tone={STATUS_TONES[order.status]}>{STATUS_LABELS[order.status]}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section
        aria-labelledby="my-shipments-heading"
        className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      >
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h3 id="my-shipments-heading" className="font-medium text-slate-900">
            My parcels
          </h3>
          <Link to="/shipments" className="text-xs font-medium text-blue-700 hover:underline">
            Tracking
          </Link>
        </div>
        {shipments.errorMessage ? (
          <p role="alert" className="text-sm text-red-700">
            {shipments.errorMessage}
          </p>
        ) : shipments.isPending ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : !shipments.data?.items.length ? (
          <p className="text-sm text-slate-500">No parcels yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {shipments.data.items.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-3 py-2">
                <div>
                  <p className="font-mono text-xs">{s.order.order_number}</p>
                  <p className="text-xs text-slate-500">
                    {s.carrier.name} · {s.tracking_number} ·{' '}
                    {s.delivered_at
                      ? `delivered ${formatDate(s.delivered_at)}`
                      : `expected ${formatDate(s.expected_delivery_date)}`}
                  </p>
                </div>
                <Badge tone={SHIPMENT_TONES[s.status]}>{s.status.replace('_', ' ')}</Badge>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
