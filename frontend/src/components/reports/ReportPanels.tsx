import type { ReactNode } from 'react'

import {
  dashboardKeys,
  getFulfillmentDashboard,
  getInventoryDashboard,
  getSupplierDashboard,
  getWarehouseDashboard,
} from '../../api/dashboardApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import type {
  DateRangeParams,
  DurationKpi,
  ProductStockKpi,
  SupplierKpi,
  ZoneUse,
} from '../../types/dashboard'
import type { OrderStatus } from '../../types/orders'
import {
  formatDays,
  formatHours,
  formatInteger,
  formatMoney,
  formatNumber,
  formatPercentage,
  plural,
} from '../../utils/format'
import { Badge } from '../common/Badge'
import { DataTable, type Column } from '../common/DataTable'
import { BarListChart } from '../dashboard/BarListChart'
import { STOCK_STATUS } from '../dashboard/dashboardFormat'
import { KpiCard } from '../dashboard/KpiCard'
import { OccupancyChart } from '../dashboard/OccupancyChart'
import { OrdersTrendChart } from '../dashboard/OrdersTrendChart'
import { StockStatusChart } from '../dashboard/StockStatusChart'
import { SupplierChart } from '../dashboard/SupplierChart'
import { STATUS_LABELS } from '../orders/orderFormat'

interface PanelProps {
  range: DateRangeParams
  /** Managers and admins see money values. */
  financials: boolean
}

const KEEP = { keepPrevious: true }
const PRODUCT_ROWS = 25 // most urgent products listed in the inventory report

function Problem({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
      {message}
    </p>
  )
}

function Tiles({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
}

// ========================================================================== inventory
export function InventoryReport({ range, financials }: PanelProps) {
  const query = useApiQuery(
    dashboardKeys.view('inventory', { ...range, limit: PRODUCT_ROWS }),
    () => getInventoryDashboard(range, PRODUCT_ROWS),
    KEEP,
  )
  const d = query.data
  const loading = query.isPending

  const categories = (d?.by_category ?? []).map((c) => ({
    label: c.category,
    value: financials ? Number(c.value_at_cost) : c.units_on_hand,
  }))
  const columns: Column<ProductStockKpi>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (p) => (
        <div>
          <p className="font-mono text-xs">{p.sku}</p>
          <p className="text-xs text-slate-500">{p.name}</p>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (p) => (
        <Badge tone={p.status === 'ok' ? 'success' : p.status === 'low' ? 'warning' : 'danger'}>
          {STOCK_STATUS[p.status].label}
        </Badge>
      ),
    },
    {
      key: 'available',
      header: 'Available',
      align: 'right',
      cell: (p) => formatInteger(p.units_available),
    },
    { key: 'min', header: 'Minimum', align: 'right', cell: (p) => formatInteger(p.min_stock) },
    { key: 'picked', header: 'Picked', align: 'right', cell: (p) => formatInteger(p.units_picked) },
    {
      key: 'demand',
      header: 'Per day',
      align: 'right',
      cell: (p) => formatNumber(p.avg_daily_demand),
    },
    {
      key: 'supply',
      header: 'Lasts',
      align: 'right',
      cell: (p) => (p.days_of_supply === null ? 'no demand' : formatDays(p.days_of_supply)),
    },
    {
      key: 'turnover',
      header: 'Turnover',
      align: 'right',
      cell: (p) => (p.turnover === null ? '—' : `${formatNumber(p.turnover)}×`),
    },
    ...(financials
      ? [
          {
            key: 'value',
            header: 'Value',
            align: 'right' as const,
            cell: (p: ProductStockKpi) => formatMoney(p.value_at_cost),
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <Problem message={query.errorMessage} />
      <Tiles>
        {financials ? (
          <KpiCard
            label="Stock value"
            isLoading={loading}
            value={formatMoney(d?.totals.value_at_cost)}
            detail={`${formatMoney(d?.totals.value_at_price)} at selling price`}
          />
        ) : (
          <KpiCard
            label="Units on hand"
            isLoading={loading}
            value={formatInteger(d?.totals.units_on_hand)}
            detail={`${plural(d?.totals.units_available, 'unit')} available`}
          />
        )}
        <KpiCard
          label="Turnover"
          isLoading={loading}
          value={d?.turnover ? `${formatNumber(d.turnover)}×` : '—'}
          detail="Cost of units picked ÷ average stock value, in the period"
        />
        <KpiCard
          label="Days of supply"
          isLoading={loading}
          value={d?.days_of_supply ? formatDays(d.days_of_supply) : '—'}
          detail={
            d?.days_of_supply
              ? 'Available stock at the picking rate of the period'
              : 'No demand in the period'
          }
        />
        <KpiCard
          label="Units picked"
          isLoading={loading}
          value={formatInteger(d?.totals.units_picked)}
          detail={`${formatInteger(d?.totals.units_reserved)} reserved · ${formatInteger(d?.totals.units_damaged)} damaged`}
        />
      </Tiles>
      <div className="grid gap-4 lg:grid-cols-2">
        <BarListChart
          title={financials ? 'Stock value per category' : 'Units per category'}
          description={financials ? 'On-hand units at purchase cost' : 'Units on hand'}
          rows={categories}
          series={[{ key: 'value', name: financials ? 'Value' : 'Units' }]}
          formatValue={(v) => (financials ? formatMoney(v) : formatInteger(v))}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
          table={{
            columns: [
              'Category',
              'Products',
              'Units',
              ...(financials ? ['Value at cost', 'Value at price'] : []),
            ],
            rows: (d?.by_category ?? []).map((c) => [
              c.category,
              c.products,
              formatInteger(c.units_on_hand),
              ...(financials ? [formatMoney(c.value_at_cost), formatMoney(c.value_at_price)] : []),
            ]),
          }}
        />
        <StockStatusChart
          counts={d?.stock_status}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
        />
      </div>
      <section aria-labelledby="products-kpi-heading" className="space-y-2">
        <h3 id="products-kpi-heading" className="font-medium">
          Products, most urgent first
          {d && d.products_total > d.products.length && (
            <span className="ml-2 text-sm font-normal text-slate-500">
              (first {d.products.length} of {d.products_total})
            </span>
          )}
        </h3>
        <DataTable
          caption="Product stock KPIs"
          columns={columns}
          rows={d?.products}
          rowKey={(p) => p.product_id}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
          onRetry={() => void query.refetch()}
          emptyMessage="No active products."
        />
      </section>
    </div>
  )
}

// ======================================================================== fulfillment
export function FulfillmentReport({ range }: PanelProps) {
  const query = useApiQuery(
    dashboardKeys.view('fulfillment', range),
    () => getFulfillmentDashboard(range),
    KEEP,
  )
  const d = query.data
  const loading = query.isPending
  const statuses = (d?.by_status ?? []).filter((s) => s.count > 0)
  const duration = (kpi: DurationKpi) =>
    kpi.orders
      ? `median ${formatHours(kpi.median_hours)} · ${plural(kpi.orders, 'order')}`
      : 'No orders measured'

  return (
    <div className="space-y-6">
      <Problem message={query.errorMessage} />
      <Tiles>
        <KpiCard
          label="Orders placed"
          isLoading={loading}
          value={formatInteger(d?.totals.placed)}
          detail={`${formatInteger(d?.totals.shipped)} shipped · ${formatInteger(d?.totals.delivered)} delivered · ${formatInteger(d?.totals.cancelled)} cancelled`}
        />
        <KpiCard
          label="Fulfillment time"
          isLoading={loading}
          value={formatHours(d?.fulfillment_time.average_hours)}
          detail={d && `Confirmed → shipped, average · ${duration(d.fulfillment_time)}`}
        />
        <KpiCard
          label="Order cycle time"
          isLoading={loading}
          value={formatHours(d?.cycle_time.average_hours)}
          detail={d && `Placed → delivered, average · ${duration(d.cycle_time)}`}
        />
        <KpiCard
          label="On-time delivery"
          isLoading={loading}
          value={formatPercentage(d?.on_time_delivery.percent)}
          detail={
            d?.on_time_delivery.total
              ? `${d.on_time_delivery.good} of ${plural(d.on_time_delivery.total, 'delivery', 'deliveries')} · picking accuracy ${formatPercentage(d.picking_accuracy.percent)}`
              : `No deliveries · picking accuracy ${formatPercentage(d?.picking_accuracy.percent)}`
          }
        />
      </Tiles>
      <OrdersTrendChart
        perDay={d?.per_day}
        isLoading={loading}
        isRefreshing={query.isPlaceholderData}
        errorMessage={query.errorMessage}
      />
      <BarListChart
        title="Orders by status"
        description="All orders, where they are now"
        rows={statuses.map((s) => ({
          label: STATUS_LABELS[s.status as OrderStatus] ?? s.status,
          value: s.count,
        }))}
        series={[{ key: 'value', name: 'Orders' }]}
        formatValue={formatInteger}
        isLoading={loading}
        isRefreshing={query.isPlaceholderData}
        errorMessage={query.errorMessage}
        emptyMessage="No orders yet."
        table={{
          columns: ['Status', 'Orders'],
          rows: statuses.map((s) => [STATUS_LABELS[s.status as OrderStatus] ?? s.status, s.count]),
        }}
      />
    </div>
  )
}

// ========================================================================== warehouse
export function WarehouseReport({ range }: PanelProps) {
  const query = useApiQuery(
    dashboardKeys.view('warehouse', range),
    () => getWarehouseDashboard(range),
    KEEP,
  )
  const d = query.data
  const loading = query.isPending
  const zones = d?.zones ?? []
  const picks = zones.reduce((sum, z) => sum + z.picks, 0)
  const units = zones.reduce((sum, z) => sum + z.units_picked, 0)
  const columns: Column<ZoneUse>[] = [
    {
      key: 'zone',
      header: 'Zone',
      cell: (z) => (
        <div>
          <p className="text-sm">
            {z.warehouse}-{z.code} · {z.name}
          </p>
          <p className="text-xs text-slate-500">
            {z.zone_type}
            {!z.is_active && ' · archived'}
          </p>
        </div>
      ),
    },
    { key: 'bins', header: 'Bins', align: 'right', cell: (z) => `${z.occupied_bins} / ${z.bins}` },
    {
      key: 'occ',
      header: 'In use',
      align: 'right',
      cell: (z) => formatPercentage(z.occupancy_percent),
    },
    {
      key: 'weight',
      header: 'Weight',
      align: 'right',
      cell: (z) => formatPercentage(z.weight_percent),
    },
    {
      key: 'volume',
      header: 'Volume',
      align: 'right',
      cell: (z) => formatPercentage(z.volume_percent),
    },
    { key: 'picks', header: 'Picks', align: 'right', cell: (z) => formatInteger(z.picks) },
    {
      key: 'units',
      header: 'Units picked',
      align: 'right',
      cell: (z) => formatInteger(z.units_picked),
    },
  ]

  return (
    <div className="space-y-6">
      <Problem message={query.errorMessage} />
      <Tiles>
        <KpiCard
          label="Bins in use"
          isLoading={loading}
          value={formatPercentage(d?.total.occupancy_percent)}
          detail={`${formatInteger(d?.total.occupied_bins)} of ${plural(d?.total.bins, 'active bin')}`}
        />
        <KpiCard
          label="Weight used"
          isLoading={loading}
          value={formatPercentage(d?.total.weight_percent)}
          detail={`${formatNumber(d?.total.used_weight_kg)} of ${formatNumber(d?.total.max_weight_kg)} kg`}
        />
        <KpiCard
          label="Volume used"
          isLoading={loading}
          value={formatPercentage(d?.total.volume_percent)}
          detail={`${formatNumber(Number(d?.total.used_volume_cm3 ?? 0) / 1e6)} of ${formatNumber((d?.total.max_volume_cm3 ?? 0) / 1e6)} m³`}
        />
        <KpiCard
          label="Picks"
          isLoading={loading}
          value={formatInteger(picks)}
          detail={`${plural(units, 'unit')} picked in the period`}
        />
      </Tiles>
      <div className="grid gap-4 lg:grid-cols-2">
        <OccupancyChart
          zones={d?.zones}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
        />
        <BarListChart
          title="Picks per zone"
          description="Pick movements from each zone's bins in the period"
          rows={zones
            .filter((z) => z.bins > 0 || z.picks > 0)
            .map((z) => ({ label: `${z.code} · ${z.name}`, value: z.picks }))}
          series={[{ key: 'value', name: 'Picks' }]}
          formatValue={formatInteger}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
          emptyMessage="No zones yet."
          table={{
            columns: ['Zone', 'Picks', 'Units picked'],
            rows: zones.map((z) => [`${z.code} · ${z.name}`, z.picks, z.units_picked]),
          }}
        />
      </div>
      <DataTable
        caption="Zones"
        columns={columns}
        rows={d?.zones}
        rowKey={(z) => z.zone_id}
        isLoading={loading}
        isRefreshing={query.isPlaceholderData}
        errorMessage={query.errorMessage}
        onRetry={() => void query.refetch()}
        emptyMessage="No zones yet."
      />
    </div>
  )
}

// ========================================================================== suppliers
export function SupplierReport({ range, financials }: PanelProps) {
  const query = useApiQuery(
    dashboardKeys.view('suppliers', range),
    () => getSupplierDashboard(range),
    KEEP,
  )
  const d = query.data
  const loading = query.isPending
  const delivered = (d?.suppliers ?? []).filter((s) => s.on_time.total > 0)
  const columns: Column<SupplierKpi>[] = [
    {
      key: 'supplier',
      header: 'Supplier',
      cell: (s) => (
        <div>
          <p className="text-sm">{s.name}</p>
          <p className="font-mono text-xs text-slate-500">
            {s.code}
            {!s.is_active && ' · archived'}
          </p>
        </div>
      ),
    },
    {
      key: 'promised',
      header: 'Promised',
      align: 'right',
      cell: (s) => formatDays(s.promised_lead_time_days),
    },
    {
      key: 'received',
      header: 'Received',
      align: 'right',
      cell: (s) => formatInteger(s.received_orders),
    },
    {
      key: 'actual',
      header: 'Actual lead time',
      align: 'right',
      cell: (s) => formatDays(s.lead_time_avg_days),
    },
    {
      key: 'stddev',
      header: 'Variation',
      align: 'right',
      cell: (s) => formatDays(s.lead_time_stddev_days),
    },
    {
      key: 'ontime',
      header: 'On time',
      align: 'right',
      cell: (s) => formatPercentage(s.on_time.percent),
    },
    {
      key: 'open',
      header: 'Open POs',
      align: 'right',
      cell: (s) => (
        <span>
          {s.open_orders}
          {s.overdue_orders > 0 && (
            <>
              {' '}
              <Badge tone="danger">{s.overdue_orders} overdue</Badge>
            </>
          )}
        </span>
      ),
    },
    ...(financials
      ? [
          {
            key: 'value',
            header: 'To arrive',
            align: 'right' as const,
            cell: (s: SupplierKpi) => formatMoney(s.open_value),
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <Problem message={query.errorMessage} />
      <Tiles>
        <KpiCard
          label="Average lead time"
          isLoading={loading}
          value={formatDays(d?.lead_time_avg_days)}
          detail={
            d?.received_orders
              ? `± ${formatDays(d.lead_time_stddev_days)} (std. dev.) · ${plural(d.received_orders, 'purchase order')} received`
              : 'No purchase order fully received in the period'
          }
        />
        <KpiCard
          label="On-time delivery"
          isLoading={loading}
          value={formatPercentage(d?.on_time.percent)}
          detail={
            d?.on_time.total
              ? `${d.on_time.good} of ${d.on_time.total} by the expected date`
              : 'Nothing received yet'
          }
        />
        <KpiCard
          label="Open purchase orders"
          isLoading={loading}
          value={formatInteger(d?.open_orders)}
          status={
            d?.overdue_orders
              ? { tone: 'serious', label: `${d.overdue_orders} overdue` }
              : undefined
          }
        />
        {financials && (
          <KpiCard
            label="Still to arrive"
            isLoading={loading}
            value={formatMoney(d?.open_value)}
            detail="Outstanding units at the agreed cost"
          />
        )}
      </Tiles>
      <div className="grid gap-4 lg:grid-cols-2">
        <SupplierChart
          suppliers={d?.suppliers}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
        />
        <BarListChart
          title="On-time delivery per supplier"
          description="Purchase orders fully received by their expected date"
          rows={delivered.map((s) => ({ label: s.code, value: Number(s.on_time.percent) }))}
          series={[{ key: 'value', name: 'On time' }]}
          domainMax={100}
          formatValue={(v) => formatPercentage(v)}
          isLoading={loading}
          isRefreshing={query.isPlaceholderData}
          errorMessage={query.errorMessage}
          emptyMessage="No purchase order was fully received in this period."
          table={{
            columns: ['Supplier', 'On time', 'Received'],
            rows: delivered.map((s) => [
              `${s.code} · ${s.name}`,
              formatPercentage(s.on_time.percent),
              `${s.on_time.good} of ${s.on_time.total}`,
            ]),
          }}
        />
      </div>
      <DataTable
        caption="Suppliers"
        columns={columns}
        rows={d?.suppliers}
        rowKey={(s) => s.supplier_id}
        isLoading={loading}
        isRefreshing={query.isPlaceholderData}
        errorMessage={query.errorMessage}
        onRetry={() => void query.refetch()}
        emptyMessage="No suppliers yet."
      />
    </div>
  )
}
