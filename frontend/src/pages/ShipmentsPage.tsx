import { AlarmClock, SearchCheck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'

import { alertKeys } from '../api/alertsApi'
import {
  cancelReturn,
  checkDelays,
  listReturns,
  listShipments,
  returnKeys,
  shipmentKeys,
} from '../api/fulfillmentApi'
import { orderKeys } from '../api/ordersApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { formatDateTime } from '../components/inventory/movementFormat'
import {
  formatDate,
  isCustomerOnly,
  isOrderManager,
  isWarehouseRole,
} from '../components/orders/orderFormat'
import { InspectDialog, ShipmentDialog } from '../components/shipments/ShipmentDialogs'
import { RETURN_TONES, SHIPMENT_TONES } from '../components/shipments/shipmentFormat'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { OrderReturn, Shipment } from '../types/orders'

const PAGE_SIZE = 25
const URL_DEFAULTS = { view: 'shipments', q: '', status: '', offset: '0' }

/** Shipments with tracking, and customer returns. Customers see their own. */
export default function ShipmentsPage() {
  const { user } = useAuth()
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const tabsId = useId()
  const manager = isOrderManager(user)

  const delays = useApiMutation(checkDelays, {
    invalidates: [shipmentKeys.all, orderKeys.all, alertKeys.all],
    successMessage: (late) =>
      late.length ? `${late.length} shipment(s) marked as delayed` : 'No shipment is overdue',
  })

  const tabs = [
    { view: 'shipments', label: 'Shipments' },
    { view: 'returns', label: 'Returns' },
  ]
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title={isCustomerOnly(user) ? 'My shipments' : 'Shipments'}
        description="Where every parcel is, and what came back."
        actions={
          manager && (
            <Button
              variant="secondary"
              icon={<AlarmClock size={16} aria-hidden="true" />}
              loading={delays.isPending}
              onClick={() => delays.mutate(undefined)}
            >
              Check delays
            </Button>
          )
        }
      />
      <div
        role="tablist"
        aria-label="Shipment views"
        className="flex gap-1 border-b border-slate-200"
      >
        {tabs.map((tab) => (
          <button
            key={tab.view}
            type="button"
            role="tab"
            id={`${tabsId}-${tab.view}`}
            aria-selected={filters.view === tab.view}
            aria-controls={`${tabsId}-panel`}
            onClick={() => setFilters({ view: tab.view, status: '', q: '' })}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
              filters.view === tab.view
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${filters.view}`}>
        {filters.view === 'returns' ? (
          <ReturnsPanel
            status={filters.status}
            onStatusChange={(status) => setFilters({ status })}
            offset={Number(filters.offset)}
            onOffsetChange={(offset) => setFilters({ offset: String(offset) })}
          />
        ) : (
          <ShipmentsPanel
            q={filters.q}
            status={filters.status}
            onChange={setFilters}
            offset={Number(filters.offset)}
          />
        )}
      </div>
    </div>
  )
}

// ========================================================================= shipments
function ShipmentsPanel({
  q,
  status,
  offset,
  onChange,
}: {
  q: string
  status: string
  offset: number
  onChange: (changes: { q?: string; status?: string; offset?: string }) => void
}) {
  const [open, setOpen] = useState<Shipment | null>(null)
  const params = { q, status, offset, limit: PAGE_SIZE }
  const shipments = useApiQuery(shipmentKeys.list(params), () => listShipments(params), {
    keepPrevious: true,
  })

  const columns: Column<Shipment>[] = [
    {
      key: 'shipped',
      header: 'Shipped',
      cell: (s) => (
        <span className="text-xs whitespace-nowrap">{formatDateTime(s.shipped_at)}</span>
      ),
    },
    {
      key: 'order',
      header: 'Order',
      cell: (s) => <span className="font-mono text-xs">{s.order.order_number}</span>,
    },
    {
      key: 'tracking',
      header: 'Tracking',
      cell: (s) => (
        <div>
          <p className="text-xs">{s.carrier.name}</p>
          <p className="font-mono text-xs">{s.tracking_number}</p>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (s) => <Badge tone={SHIPMENT_TONES[s.status]}>{s.status.replace('_', ' ')}</Badge>,
    },
    {
      key: 'expected',
      header: 'Expected',
      cell: (s) => (
        <span className="text-xs whitespace-nowrap">
          {s.delivered_at
            ? `delivered ${formatDate(s.delivered_at)}`
            : formatDate(s.expected_delivery_date)}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search shipments"
          placeholder="Tracking or order number"
          value={q}
          onChange={(value) => onChange({ q: value })}
        />
        <FilterSelect
          label="Status"
          value={status}
          onChange={(value) => onChange({ status: value })}
          options={[
            { value: '', label: 'All statuses' },
            { value: 'dispatched', label: 'Dispatched' },
            { value: 'in_transit', label: 'In transit' },
            { value: 'delayed', label: 'Delayed' },
            { value: 'delivered', label: 'Delivered' },
          ]}
        />
      </div>
      <DataTable
        caption="Shipments"
        columns={columns}
        rows={shipments.data?.items}
        rowKey={(s) => s.id}
        isLoading={shipments.isPending}
        isRefreshing={shipments.isPlaceholderData}
        errorMessage={shipments.errorMessage}
        onRetry={() => void shipments.refetch()}
        emptyMessage="No shipments match."
        onRowClick={setOpen}
        pagination={
          shipments.data && {
            offset: shipments.data.offset,
            limit: shipments.data.limit,
            total: shipments.data.total,
            onChange: (next) => onChange({ offset: String(next) }),
          }
        }
      />
      <ShipmentDialog shipment={open} onClose={() => setOpen(null)} />
    </div>
  )
}

// =========================================================================== returns
function ReturnsPanel({
  status,
  onStatusChange,
  offset,
  onOffsetChange,
}: {
  status: string
  onStatusChange: (status: string) => void
  offset: number
  onOffsetChange: (offset: number) => void
}) {
  const { user } = useAuth()
  const warehouse = isWarehouseRole(user)
  const [inspecting, setInspecting] = useState<OrderReturn | null>(null)
  const params = { status, offset, limit: PAGE_SIZE }
  const returns = useApiQuery(returnKeys.list(params), () => listReturns(params), {
    keepPrevious: true,
  })
  const cancel = useApiMutation(cancelReturn, {
    invalidates: [returnKeys.all, orderKeys.all],
    successMessage: (r) => `Return ${r.return_number} cancelled`,
  })

  const columns: Column<OrderReturn>[] = [
    {
      key: 'number',
      header: 'Return',
      cell: (r) => (
        <div>
          <p className="font-mono text-xs font-medium">{r.return_number}</p>
          <p className="text-xs text-slate-500">{formatDate(r.created_at)}</p>
        </div>
      ),
    },
    {
      key: 'order',
      header: 'Order',
      cell: (r) => (
        <Link
          to={`/orders/${r.order_id}`}
          className="font-mono text-xs text-blue-700 hover:underline"
        >
          {r.order_number}
        </Link>
      ),
    },
    {
      key: 'items',
      header: 'Items',
      cell: (r) => (
        <div className="text-xs">
          {r.items.map((i) => (
            <p key={i.id}>
              {i.quantity} × {i.product.sku}
              {i.condition && <span className="text-slate-500"> · {i.condition}</span>}
            </p>
          ))}
        </div>
      ),
    },
    { key: 'reason', header: 'Reason', cell: (r) => <span className="text-xs">{r.reason}</span> },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => <Badge tone={RETURN_TONES[r.status]}>{r.status}</Badge>,
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (r) =>
        r.status === 'open' && (
          <div className="flex justify-end gap-1">
            {warehouse && (
              <Button
                size="sm"
                icon={<SearchCheck size={14} aria-hidden="true" />}
                aria-label={`Inspect ${r.return_number}`}
                onClick={() => setInspecting(r)}
              >
                Inspect
              </Button>
            )}
            {(isOrderManager(user) || isCustomerOnly(user)) && (
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Cancel ${r.return_number}`}
                onClick={() => cancel.mutate(r.id)}
              >
                Cancel
              </Button>
            )}
          </div>
        ),
    },
  ]

  return (
    <div className="space-y-4">
      <FilterSelect
        label="Return status"
        value={status}
        onChange={onStatusChange}
        options={[
          { value: '', label: 'All returns' },
          { value: 'open', label: 'Open' },
          { value: 'completed', label: 'Completed' },
          { value: 'cancelled', label: 'Cancelled' },
        ]}
      />
      <DataTable
        caption="Returns"
        columns={columns}
        rows={returns.data?.items}
        rowKey={(r) => r.id}
        isLoading={returns.isPending}
        isRefreshing={returns.isPlaceholderData}
        errorMessage={returns.errorMessage}
        onRetry={() => void returns.refetch()}
        emptyMessage="No returns."
        pagination={
          returns.data && {
            offset: returns.data.offset,
            limit: returns.data.limit,
            total: returns.data.total,
            onChange: onOffsetChange,
          }
        }
      />
      <InspectDialog ret={inspecting} onClose={() => setInspecting(null)} />
    </div>
  )
}
