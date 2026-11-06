import { AlertCircle, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { alertKeys } from '../../api/alertsApi'
import {
  addShipmentEvent,
  inspectReturn,
  openReturn,
  returnKeys,
  shipmentKeys,
  type TrackingEventType,
} from '../../api/fulfillmentApi'
import { inventoryKeys } from '../../api/inventoryApi'
import { orderKeys } from '../../api/ordersApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useAuth } from '../../hooks/useAuth'
import type { Order, OrderReturn, Shipment } from '../../types/orders'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { DetailItem } from '../common/PageHeader'
import { SelectField, TextField } from '../form/fields'
import { formatDateTime } from '../inventory/movementFormat'
import { formatDate, isWarehouseRole } from '../orders/orderFormat'
import { EVENT_LABELS, SHIPMENT_TONES } from './shipmentFormat'

const INVALIDATES = [
  shipmentKeys.all,
  returnKeys.all,
  orderKeys.all,
  inventoryKeys.all,
  alertKeys.all,
]

function Problem({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p
      role="alert"
      className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      <AlertCircle size={16} aria-hidden="true" />
      {message}
    </p>
  )
}

// ======================================================================= shipment
export function ShipmentDialog({
  shipment,
  onClose,
}: {
  shipment: Shipment | null
  onClose: () => void
}) {
  return shipment ? <ShipmentView shipment={shipment} onClose={onClose} /> : null
}

const TRACKING_EVENTS: TrackingEventType[] = [
  'in_transit',
  'out_for_delivery',
  'delayed',
  'delivered',
  'exception',
]

function ShipmentView({ shipment, onClose }: { shipment: Shipment; onClose: () => void }) {
  const { user } = useAuth()
  const [current, setCurrent] = useState(shipment)
  const [eventType, setEventType] = useState<TrackingEventType>('in_transit')
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const canTrack = isWarehouseRole(user) && current.status !== 'delivered'

  const add = useApiMutation(
    () =>
      addShipmentEvent(current.id, {
        event_type: eventType,
        location: location.trim() || undefined,
        description: description.trim() || undefined,
      }),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: (s) => `${s.tracking_number}: ${EVENT_LABELS[eventType]}`,
      onSuccess: (s) => {
        setCurrent(s)
        setLocation('')
        setDescription('')
      },
    },
  )

  const submit = () => {
    if (eventType === 'exception' && !description.trim())
      return setError('Describe the exception, e.g. address not found')
    setError(null)
    add.mutate(undefined)
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Shipment ${current.tracking_number}`}
      description={`Order ${current.order.order_number} · ${current.carrier.name}`}
      size="lg"
    >
      <div className="space-y-5">
        <dl className="grid gap-4 sm:grid-cols-4">
          <DetailItem label="Status">
            <Badge tone={SHIPMENT_TONES[current.status]}>{current.status.replace('_', ' ')}</Badge>
          </DetailItem>
          <DetailItem label="Shipped">{formatDateTime(current.shipped_at)}</DetailItem>
          <DetailItem label="Expected">{formatDate(current.expected_delivery_date)}</DetailItem>
          <DetailItem label="Delivered">
            {current.delivered_at ? formatDateTime(current.delivered_at) : '—'}
          </DetailItem>
        </dl>
        <div className="flex flex-wrap gap-4 text-sm">
          <Link to={`/orders/${current.order.id}`} className="text-blue-700 hover:underline">
            Open order {current.order.order_number}
          </Link>
          {current.tracking_url && (
            <a
              href={current.tracking_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-blue-700 hover:underline"
            >
              Carrier tracking <ExternalLink size={12} aria-hidden="true" />
            </a>
          )}
        </div>
        <ol aria-label="Tracking events" className="space-y-2 border-l-2 border-slate-200 pl-4">
          {[...current.events].reverse().map((event) => (
            <li key={event.id} className="text-sm">
              <p>
                <span className="font-medium">
                  {EVENT_LABELS[event.event_type as keyof typeof EVENT_LABELS] ?? event.event_type}
                </span>
                {event.location && <span> · {event.location}</span>}
              </p>
              <p className="text-xs text-slate-500">
                {formatDateTime(event.occurred_at)}
                {event.description && ` — ${event.description}`}
              </p>
            </li>
          ))}
        </ol>
        {canTrack && (
          <fieldset className="space-y-3 rounded-xl border border-slate-200 p-4">
            <legend className="px-1 text-sm font-medium">Add a tracking update</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                label="What happened?"
                value={eventType}
                onChange={(event) => setEventType(event.target.value as TrackingEventType)}
                options={TRACKING_EVENTS.map((t) => ({ value: t, label: EVENT_LABELS[t] }))}
              />
              <TextField
                label="Where"
                value={location}
                maxLength={120}
                onChange={(event) => setLocation(event.target.value)}
              />
            </div>
            <TextField
              label="Details"
              value={description}
              maxLength={255}
              onChange={(event) => setDescription(event.target.value)}
              hint={eventType === 'exception' ? 'Required for an exception' : 'Optional'}
            />
            <Problem message={error ?? add.errorMessage} />
            <div className="flex justify-end">
              <Button loading={add.isPending} onClick={submit}>
                Add update
              </Button>
            </div>
          </fieldset>
        )}
      </div>
    </Modal>
  )
}

// ==================================================================== open return
export function ReturnDialog({ order, onClose }: { order: Order | null; onClose: () => void }) {
  return order ? <ReturnForm order={order} onClose={onClose} /> : null
}

function ReturnForm({ order, onClose }: { order: Order; onClose: () => void }) {
  const lines = order.items.filter((i) => i.quantity_shipped - i.quantity_returned > 0)
  const [quantities, setQuantities] = useState<Record<number, string>>({})
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const open = useApiMutation(openReturn, {
    invalidates: INVALIDATES,
    toastOnError: false,
    successMessage: (r) => `Return ${r.return_number} opened`,
    onSuccess: onClose,
  })

  const submit = () => {
    const items = []
    for (const line of lines) {
      const text = (quantities[line.product.id] ?? '').trim()
      if (!text || text === '0') continue
      const max = line.quantity_shipped - line.quantity_returned
      if (!/^\d+$/.test(text) || Number(text) > max)
        return setError(`${line.product.sku}: between 0 and ${max}`)
      items.push({ product_id: line.product.id, quantity: Number(text) })
    }
    if (items.length === 0) return setError('Choose at least one item to return')
    if (reason.trim().length < 3) return setError('Tell us why (at least 3 characters)')
    setError(null)
    open.mutate({ order_id: order.id, reason: reason.trim(), items })
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Return items of ${order.order_number}`}
      description="Choose what goes back and why. Returns already opened are taken into account."
      dismissible={!open.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={open.isPending}>
            Cancel
          </Button>
          <Button loading={open.isPending} onClick={submit}>
            Open return
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {lines.map((line) => (
            <li key={line.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <div className="flex-1">
                <p className="font-mono text-xs">{line.product.sku}</p>
                <p>{line.product.name}</p>
                <p className="text-xs text-slate-500">
                  up to {line.quantity_shipped - line.quantity_returned}
                </p>
              </div>
              <input
                aria-label={`Return quantity of ${line.product.sku}`}
                inputMode="numeric"
                placeholder="0"
                value={quantities[line.product.id] ?? ''}
                onChange={(event) =>
                  setQuantities((all) => ({ ...all, [line.product.id]: event.target.value }))
                }
                className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-right"
              />
            </li>
          ))}
        </ul>
        <TextField
          label="Reason"
          required
          value={reason}
          maxLength={255}
          onChange={(event) => setReason(event.target.value)}
        />
        <Problem message={error ?? open.errorMessage} />
      </div>
    </Modal>
  )
}

// ======================================================================== inspect
export function InspectDialog({ ret, onClose }: { ret: OrderReturn | null; onClose: () => void }) {
  return ret ? <InspectForm ret={ret} onClose={onClose} /> : null
}

function InspectForm({ ret, onClose }: { ret: OrderReturn; onClose: () => void }) {
  const [conditions, setConditions] = useState<Record<number, 'restock' | 'damaged'>>(() =>
    Object.fromEntries(ret.items.map((i) => [i.product.id, 'restock'])),
  )
  const [notes, setNotes] = useState<Record<number, string>>({})

  const inspect = useApiMutation(
    () =>
      inspectReturn(
        ret.id,
        ret.items.map((i) => ({
          product_id: i.product.id,
          condition: conditions[i.product.id],
          note: notes[i.product.id]?.trim() || undefined,
        })),
      ),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: (r) => `Return ${r.return_number} inspected — stock updated`,
      onSuccess: onClose,
    },
  )

  return (
    <Modal
      open
      onClose={onClose}
      title={`Inspect return ${ret.return_number}`}
      description={`Order ${ret.order_number} · ${ret.reason}`}
      dismissible={!inspect.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={inspect.isPending}>
            Cancel
          </Button>
          <Button loading={inspect.isPending} onClick={() => inspect.mutate(undefined)}>
            Book into stock
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {ret.items.map((item) => (
          <div key={item.id} className="space-y-2 rounded-lg border border-slate-200 p-3">
            <p className="text-sm">
              <span className="font-medium">{item.quantity} ×</span>{' '}
              <span className="font-mono text-xs">{item.product.sku}</span> {item.product.name}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                label={`Condition of ${item.product.sku}`}
                value={conditions[item.product.id]}
                onChange={(event) =>
                  setConditions((all) => ({
                    ...all,
                    [item.product.id]: event.target.value as 'restock' | 'damaged',
                  }))
                }
                options={[
                  { value: 'restock', label: 'As new — back into stock' },
                  { value: 'damaged', label: 'Damaged — into stock as damaged' },
                ]}
              />
              <TextField
                label="Note"
                value={notes[item.product.id] ?? ''}
                maxLength={255}
                onChange={(event) =>
                  setNotes((all) => ({ ...all, [item.product.id]: event.target.value }))
                }
              />
            </div>
          </div>
        ))}
        <p className="text-xs text-slate-500">
          Units go into a bin of the returns zone. Damaged units can be written off later.
        </p>
        <Problem message={inspect.errorMessage} />
      </div>
    </Modal>
  )
}
