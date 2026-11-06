import { Play, ScanLine, Truck } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'

import { alertKeys } from '../api/alertsApi'
import {
  fulfillmentKeys,
  listPackingTasks,
  listPickingTasks,
  startPacking,
  startPicking,
} from '../api/fulfillmentApi'
import { orderKeys } from '../api/ordersApi'
import { Badge, type BadgeTone } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { PageHeader } from '../components/common/PageHeader'
import { CheckboxField } from '../components/form/fields'
import { PackDialog, PickDialog, ShipDialog } from '../components/fulfillment/FulfillmentDialogs'
import { PRIORITY_TONES } from '../components/orders/orderFormat'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { OrderRef, PackingTask, PickingTask } from '../types/orders'

const URL_DEFAULTS = { view: 'picking', mine: '', offset: '0' }
const INVALIDATES = [fulfillmentKeys.all, orderKeys.all, alertKeys.all]

const TASK_TONES: Record<string, BadgeTone> = {
  pending: 'neutral',
  in_progress: 'info',
  completed: 'success',
  short: 'warning',
}

function OrderCell({ order }: { order: OrderRef }) {
  return (
    <div className="whitespace-nowrap">
      <Link to={`/orders/${order.id}`} className="font-mono text-xs text-blue-700 hover:underline">
        {order.order_number}
      </Link>
      {order.priority !== 'normal' && (
        <span className="ml-2">
          <Badge tone={PRIORITY_TONES[order.priority]}>{order.priority}</Badge>
        </span>
      )}
    </div>
  )
}

/** Staff work queue: pick along the route, pack, and hand to a carrier. */
export default function FulfillmentPage() {
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const tabsId = useId()
  const tabs = [
    { view: 'picking', label: 'Picking' },
    { view: 'packing', label: 'Packing & shipping' },
  ]
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Fulfillment"
        description="Urgent orders first; each order's picks follow one route that ends at packing."
      />
      <div
        role="tablist"
        aria-label="Fulfillment views"
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
            onClick={() => setFilters({ view: tab.view, mine: '' })}
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
        {filters.view === 'packing' ? (
          <PackingPanel />
        ) : (
          <PickingPanel
            mine={filters.mine === '1'}
            onMineChange={(mine) => setFilters({ mine: mine ? '1' : '' })}
            offset={Number(filters.offset)}
            onOffsetChange={(offset) => setFilters({ offset: String(offset) })}
          />
        )}
      </div>
    </div>
  )
}

// ============================================================================ picking
function PickingPanel({
  mine,
  onMineChange,
  offset,
  onOffsetChange,
}: {
  mine: boolean
  onMineChange: (mine: boolean) => void
  offset: number
  onOffsetChange: (offset: number) => void
}) {
  const { user } = useAuth()
  const [picking, setPicking] = useState<PickingTask | null>(null)
  const params = { status: 'open', mine, offset, limit: 50 }
  const tasks = useApiQuery(fulfillmentKeys.picking(params), () => listPickingTasks(params), {
    keepPrevious: true,
    refetchInterval: 30_000, // new orders arrive while people work
  })

  const start = useApiMutation(startPicking, {
    invalidates: INVALIDATES,
    onSuccess: (task) => setPicking(task),
  })

  const columns: Column<PickingTask>[] = [
    { key: 'order', header: 'Order', cell: (t) => <OrderCell order={t.order} /> },
    { key: 'stop', header: 'Stop', align: 'right', cell: (t) => t.sequence },
    {
      key: 'bin',
      header: 'Bin',
      cell: (t) => (
        <span className="font-mono text-xs font-semibold whitespace-nowrap">
          {t.bin.location_code}
        </span>
      ),
    },
    {
      key: 'product',
      header: 'Product',
      cell: (t) => (
        <div>
          <p className="font-mono text-xs">{t.product.sku}</p>
          <p className="text-xs text-slate-500">{t.product.name}</p>
        </div>
      ),
    },
    { key: 'qty', header: 'Qty', align: 'right', cell: (t) => t.quantity },
    {
      key: 'status',
      header: 'Status',
      cell: (t) => (
        <div>
          <Badge tone={TASK_TONES[t.status]}>{t.status.replace('_', ' ')}</Badge>
          {t.assigned_to && (
            <p className="mt-1 text-xs text-slate-500">{t.assigned_to.full_name}</p>
          )}
        </div>
      ),
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (t) =>
        t.status === 'pending' ? (
          <Button
            size="sm"
            icon={<Play size={14} aria-hidden="true" />}
            aria-label={`Start stop ${t.sequence} of ${t.order.order_number}`}
            loading={start.isPending && start.variables === t.id}
            onClick={() => start.mutate(t.id)}
          >
            Start
          </Button>
        ) : (
          <Button
            size="sm"
            icon={<ScanLine size={14} aria-hidden="true" />}
            aria-label={`Confirm stop ${t.sequence} of ${t.order.order_number}`}
            variant={t.assigned_to?.id === user?.id ? 'primary' : 'secondary'}
            onClick={() => setPicking(t)}
          >
            Confirm
          </Button>
        ),
    },
  ]

  return (
    <div className="space-y-4">
      <CheckboxField
        label="Only tasks I started"
        checked={mine}
        onChange={(event) => onMineChange(event.target.checked)}
      />
      <DataTable
        caption="Picking tasks"
        columns={columns}
        rows={tasks.data?.items}
        rowKey={(t) => t.id}
        isLoading={tasks.isPending}
        isRefreshing={tasks.isPlaceholderData}
        errorMessage={tasks.errorMessage}
        onRetry={() => void tasks.refetch()}
        emptyMessage="Nothing to pick right now."
        pagination={
          tasks.data && {
            offset: tasks.data.offset,
            limit: tasks.data.limit,
            total: tasks.data.total,
            onChange: onOffsetChange,
          }
        }
      />
      <PickDialog task={picking} onClose={() => setPicking(null)} />
    </div>
  )
}

// ============================================================================ packing
function PackingPanel() {
  const [packing, setPacking] = useState<PackingTask | null>(null)
  const [shipping, setShipping] = useState<OrderRef | null>(null)
  const open = useApiQuery(fulfillmentKeys.packing('open'), () => listPackingTasks('open'), {
    refetchInterval: 30_000,
  })
  const done = useApiQuery(fulfillmentKeys.packing('completed'), () =>
    listPackingTasks('completed'),
  )
  const readyToShip = done.data?.items.filter((t) => t.order.status === 'packed')

  const start = useApiMutation(startPacking, {
    invalidates: INVALIDATES,
    onSuccess: (task) => setPacking(task),
  })

  const packColumns: Column<PackingTask>[] = [
    { key: 'order', header: 'Order', cell: (t) => <OrderCell order={t.order} /> },
    {
      key: 'lines',
      header: 'Items',
      cell: (t) => (
        <span className="text-xs">
          {t.lines.map((l) => `${l.quantity_picked} × ${l.product.sku}`).join(', ')}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (t) => (
        <div>
          <Badge tone={TASK_TONES[t.status]}>{t.status.replace('_', ' ')}</Badge>
          {t.packed_by && <p className="mt-1 text-xs text-slate-500">{t.packed_by.full_name}</p>}
        </div>
      ),
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (t) =>
        t.status === 'pending' ? (
          <Button
            size="sm"
            icon={<Play size={14} aria-hidden="true" />}
            aria-label={`Start packing ${t.order.order_number}`}
            onClick={() => start.mutate(t.id)}
          >
            Start
          </Button>
        ) : (
          <Button
            size="sm"
            aria-label={`Pack ${t.order.order_number}`}
            onClick={() => setPacking(t)}
          >
            Pack
          </Button>
        ),
    },
  ]

  const shipColumns: Column<PackingTask>[] = [
    { key: 'order', header: 'Order', cell: (t) => <OrderCell order={t.order} /> },
    {
      key: 'parcels',
      header: 'Parcels',
      cell: (t) => `${t.package_count} · ${t.weight_kg} kg`,
    },
    {
      key: 'action',
      header: '',
      align: 'right',
      cell: (t) => (
        <Button
          size="sm"
          icon={<Truck size={14} aria-hidden="true" />}
          aria-label={`Ship ${t.order.order_number}`}
          onClick={() => setShipping(t.order)}
        >
          Ship
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-8">
      <section aria-labelledby="pack-heading" className="space-y-3">
        <h2 id="pack-heading" className="font-medium">
          To pack
        </h2>
        <DataTable
          caption="Packing tasks"
          columns={packColumns}
          rows={open.data?.items}
          rowKey={(t) => t.id}
          isLoading={open.isPending}
          errorMessage={open.errorMessage}
          onRetry={() => void open.refetch()}
          emptyMessage="Nothing waiting at the packing station."
        />
      </section>
      <section aria-labelledby="ship-heading" className="space-y-3">
        <h2 id="ship-heading" className="font-medium">
          Ready to ship
        </h2>
        <DataTable
          caption="Packed orders"
          columns={shipColumns}
          rows={readyToShip}
          rowKey={(t) => t.id}
          isLoading={done.isPending}
          errorMessage={done.errorMessage}
          emptyMessage="No packed orders waiting for a carrier."
        />
      </section>
      <PackDialog
        task={packing}
        onClose={() => setPacking(null)}
        onPacked={(task) => {
          setPacking(null)
          setShipping(task.order) // straight on to the carrier
        }}
      />
      <ShipDialog order={shipping} onClose={() => setShipping(null)} />
    </div>
  )
}
