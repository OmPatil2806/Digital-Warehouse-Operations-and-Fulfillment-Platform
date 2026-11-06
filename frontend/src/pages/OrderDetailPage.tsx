import { ArrowLeft, ExternalLink, PackageCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { getErrorMessage } from '../api/apiClient'
import { alertKeys } from '../api/alertsApi'
import { listReturns, returnKeys } from '../api/fulfillmentApi'
import { inventoryKeys } from '../api/inventoryApi'
import {
  allocateOrder,
  getOrder,
  getOrderShipment,
  orderAction,
  orderKeys,
  type OrderAction,
} from '../api/ordersApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { DetailItem, PageHeader } from '../components/common/PageHeader'
import { formatDateTime } from '../components/inventory/movementFormat'
import { NoteDialog } from '../components/inventory/NoteDialog'
import {
  formatDate,
  isCustomerOnly,
  isOrderManager,
  isWarehouseRole,
  PRIORITY_TONES,
  STATUS_LABELS,
  STATUS_TONES,
} from '../components/orders/orderFormat'
import { InspectDialog, ReturnDialog } from '../components/shipments/ShipmentDialogs'
import { RETURN_TONES } from '../components/shipments/shipmentFormat'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import type { Order, OrderItem, OrderReturn } from '../types/orders'
import { formatMoney } from '../utils/format'
import NotFoundPage from './NotFoundPage'

const ITEM_COLUMNS: Column<OrderItem>[] = [
  {
    key: 'product',
    header: 'Product',
    cell: (i) => (
      <div>
        <p className="font-mono text-xs">{i.product.sku}</p>
        <p>{i.product.name}</p>
      </div>
    ),
  },
  { key: 'qty', header: 'Ordered', align: 'right', cell: (i) => i.quantity },
  { key: 'reserved', header: 'Reserved', align: 'right', cell: (i) => i.quantity_reserved || '—' },
  { key: 'picked', header: 'Picked', align: 'right', cell: (i) => i.quantity_picked || '—' },
  { key: 'shipped', header: 'Shipped', align: 'right', cell: (i) => i.quantity_shipped || '—' },
  { key: 'returned', header: 'Returned', align: 'right', cell: (i) => i.quantity_returned || '—' },
  { key: 'price', header: 'Price', align: 'right', cell: (i) => formatMoney(i.unit_price) },
  { key: 'total', header: 'Total', align: 'right', cell: (i) => formatMoney(i.line_total) },
]

type Asking = { action: 'cancel' | 'hold'; title: string; label: string } | null

export default function OrderDetailPage() {
  const id = Number(useParams().orderId)
  const order = useApiQuery(orderKeys.detail(id), () => getOrder(id), {
    enabled: Number.isInteger(id),
  })

  if (!Number.isInteger(id) || (order.error && getErrorMessage(order.error) === 'Order not found'))
    return <NotFoundPage />
  if (order.isPending)
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading…
      </p>
    )
  if (!order.data)
    return (
      <p role="alert" className="text-sm text-red-700">
        {order.errorMessage}
      </p>
    )
  return <OrderView order={order.data} />
}

function OrderView({ order }: { order: Order }) {
  const { user } = useAuth()
  const [asking, setAsking] = useState<Asking>(null)
  const [returning, setReturning] = useState(false)
  const [inspecting, setInspecting] = useState<OrderReturn | null>(null)
  const manager = isOrderManager(user)
  const warehouse = isWarehouseRole(user)
  const owner = isCustomerOnly(user) // the API only shows a customer their own orders
  const next = new Set(order.next_statuses)
  const invalidates = [orderKeys.all, inventoryKeys.all, alertKeys.all]

  const act = useApiMutation(
    ({ action, reason }: { action: OrderAction; reason?: string }) =>
      orderAction(order.id, action, reason),
    {
      invalidates,
      successMessage: (o) => `${o.order_number}: ${STATUS_LABELS[o.status]}`,
      onSuccess: () => setAsking(null),
    },
  )
  const allocate = useApiMutation(() => allocateOrder(order.id), {
    invalidates,
    successMessage: (tasks) => `Picking route created (${tasks.length} task(s))`,
  })

  const returns = useApiQuery(
    [...returnKeys.all, 'order', order.id],
    () => listReturns({ order_id: order.id }),
    { enabled: ['delivered', 'returned'].includes(order.status) },
  )
  const shipment = useApiQuery(orderKeys.shipment(order.id), () => getOrderShipment(order.id), {
    enabled: ['shipped', 'delayed', 'delivered', 'returned'].includes(order.status),
  })

  const actions = [
    {
      show: order.status === 'created' && next.has('confirmed') && (manager || owner),
      label: 'Confirm order',
      primary: true,
      run: () => act.mutate({ action: 'confirm' }),
    },
    {
      show: order.status === 'inventory_reserved' && warehouse,
      label: 'Create picking route',
      primary: true,
      run: () => allocate.mutate(undefined),
    },
    {
      show: ['backordered', 'partially_allocated'].includes(order.status) && manager,
      label: 'Retry reservation',
      run: () => act.mutate({ action: 'reserve' }),
    },
    {
      show: order.status === 'on_hold' && manager,
      label: 'Release hold',
      primary: true,
      run: () => act.mutate({ action: 'release' }),
    },
    {
      show: next.has('on_hold') && manager,
      label: 'Put on hold',
      run: () =>
        setAsking({ action: 'hold', title: 'Put the order on hold', label: 'Why is it on hold?' }),
    },
    {
      show: next.has('cancelled') && (manager || owner),
      label: 'Cancel order',
      danger: true,
      run: () =>
        setAsking({
          action: 'cancel',
          title: `Cancel ${order.order_number}?`,
          label: 'Why is the order cancelled?',
        }),
    },
    {
      show:
        ['delivered', 'returned'].includes(order.status) &&
        order.items.some((i) => i.quantity_shipped > i.quantity_returned),
      label: 'Return items',
      run: () => setReturning(true),
    },
  ].filter((a) => a.show)

  const address = [
    order.ship_to_address,
    [order.ship_to_postal_code, order.ship_to_city].filter(Boolean).join(' '),
    order.ship_to_country,
  ].filter(Boolean)

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <Link
        to="/orders"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft size={14} aria-hidden="true" /> All orders
      </Link>

      <PageHeader
        title={`Order ${order.order_number}`}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONES[order.status]}>{STATUS_LABELS[order.status]}</Badge>
            {order.priority !== 'normal' && (
              <Badge tone={PRIORITY_TONES[order.priority]}>{order.priority} priority</Badge>
            )}
            <span>
              {order.customer.name} ({order.customer.code})
            </span>
          </span>
        }
        actions={
          actions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {actions.map((a) => (
                <Button
                  key={a.label}
                  variant={a.danger ? 'danger' : a.primary ? 'primary' : 'secondary'}
                  loading={(act.isPending || allocate.isPending) && a.primary}
                  disabled={act.isPending || allocate.isPending}
                  onClick={a.run}
                >
                  {a.label}
                </Button>
              ))}
            </div>
          )
        }
      />

      {(order.status === 'backordered' || order.status === 'partially_allocated') && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Not all units are in stock yet. The missing units are reserved automatically as soon as
          goods arrive.
        </p>
      )}
      {order.status === 'cancelled' && order.cancel_reason && (
        <p className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">
          Cancelled: {order.cancel_reason}
        </p>
      )}

      <dl className="grid gap-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:grid-cols-4">
        <DetailItem label="Placed">{formatDateTime(order.created_at)}</DetailItem>
        <DetailItem label="Wanted by">{formatDate(order.requested_delivery_date)}</DetailItem>
        <DetailItem label="Ship to">
          <span className="block">{order.ship_to_name}</span>
          {address.map((line) => (
            <span key={line} className="block text-slate-600">
              {line}
            </span>
          ))}
        </DetailItem>
        <DetailItem label="Total">{formatMoney(order.subtotal)}</DetailItem>
        {order.warehouse && (
          <DetailItem label="Warehouse">
            {order.warehouse.code} · {order.warehouse.name}
          </DetailItem>
        )}
        {order.notes && (
          <div className="sm:col-span-3">
            <DetailItem label="Notes">{order.notes}</DetailItem>
          </div>
        )}
      </dl>

      <section aria-labelledby="items-heading" className="space-y-3">
        <h2 id="items-heading" className="font-medium">
          Items
        </h2>
        <DataTable
          caption="Order lines"
          columns={ITEM_COLUMNS}
          rows={order.items}
          rowKey={(i) => i.id}
        />
      </section>

      {shipment.data && (
        <section
          aria-labelledby="shipment-heading"
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="shipment-heading" className="flex items-center gap-2 font-medium">
              <PackageCheck size={16} aria-hidden="true" /> Shipment
            </h2>
            {shipment.data.tracking_url && (
              <a
                href={shipment.data.tracking_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline"
              >
                Track with {shipment.data.carrier.name}
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
          </div>
          <dl className="grid gap-4 sm:grid-cols-4">
            <DetailItem label="Carrier">{shipment.data.carrier.code}</DetailItem>
            <DetailItem label="Tracking number">
              <span className="font-mono">{shipment.data.tracking_number}</span>
            </DetailItem>
            <DetailItem label="Expected">
              {formatDate(shipment.data.expected_delivery_date)}
            </DetailItem>
            <DetailItem label="Parcels">
              {shipment.data.package_count} · {shipment.data.weight_kg} kg
            </DetailItem>
          </dl>
          <ol aria-label="Tracking events" className="space-y-1 text-sm">
            {shipment.data.events.map((event) => (
              <li key={event.id} className="flex flex-wrap gap-x-3">
                <span className="text-slate-500">{formatDateTime(event.occurred_at)}</span>
                <span className="font-medium">{event.event_type.replace(/_/g, ' ')}</span>
                {event.location && <span>{event.location}</span>}
                {event.description && <span className="text-slate-500">{event.description}</span>}
              </li>
            ))}
          </ol>
        </section>
      )}

      {returns.data && returns.data.items.length > 0 && (
        <section aria-labelledby="returns-heading" className="space-y-3">
          <h2 id="returns-heading" className="font-medium">
            Returns
          </h2>
          <ul className="space-y-2">
            {returns.data.items.map((ret) => (
              <li
                key={ret.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"
              >
                <div>
                  <p>
                    <span className="font-mono text-xs font-medium">{ret.return_number}</span>{' '}
                    <Badge tone={RETURN_TONES[ret.status]}>{ret.status}</Badge>
                  </p>
                  <p className="text-xs text-slate-500">
                    {ret.items
                      .map(
                        (i) =>
                          `${i.quantity} × ${i.product.sku}${i.condition ? ` (${i.condition})` : ''}`,
                      )
                      .join(', ')}{' '}
                    — {ret.reason}
                  </p>
                </div>
                {ret.status === 'open' && warehouse && (
                  <Button size="sm" onClick={() => setInspecting(ret)}>
                    Inspect
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="timeline-heading" className="space-y-3">
        <h2 id="timeline-heading" className="font-medium">
          Timeline
        </h2>
        <ol aria-label="Status timeline" className="space-y-3 border-l-2 border-slate-200 pl-4">
          {[...order.history].reverse().map((entry, index) => (
            <li key={`${entry.created_at}-${index}`} className="relative">
              <span
                aria-hidden="true"
                className="absolute top-1.5 -left-[1.4rem] h-2.5 w-2.5 rounded-full bg-blue-600"
              />
              <p className="text-sm">
                <span className="font-medium">{STATUS_LABELS[entry.to_status]}</span>
                {entry.note && <span className="text-slate-600"> — {entry.note}</span>}
              </p>
              <p className="text-xs text-slate-500">
                {formatDateTime(entry.created_at)}
                {warehouse && ` · ${entry.changed_by?.full_name ?? 'System'}`}
              </p>
            </li>
          ))}
        </ol>
      </section>

      <ReturnDialog order={returning ? order : null} onClose={() => setReturning(false)} />
      <InspectDialog ret={inspecting} onClose={() => setInspecting(null)} />
      <NoteDialog
        open={asking !== null}
        title={asking?.title ?? ''}
        label={asking?.label ?? ''}
        confirmLabel={asking?.action === 'hold' ? 'Put on hold' : 'Cancel order'}
        loading={act.isPending}
        onCancel={() => setAsking(null)}
        onConfirm={(reason) => asking && act.mutate({ action: asking.action, reason })}
      />
    </div>
  )
}
