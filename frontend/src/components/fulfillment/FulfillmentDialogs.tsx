import { AlertCircle, CheckCircle2, XCircle } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { alertKeys } from '../../api/alertsApi'
import {
  completePacking,
  completePicking,
  createShipment,
  fulfillmentKeys,
  listCarriers,
} from '../../api/fulfillmentApi'
import { inventoryKeys } from '../../api/inventoryApi'
import { orderKeys } from '../../api/ordersApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { PackingTask, PickingTask } from '../../types/orders'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { SelectField, TextField } from '../form/fields'

const INVALIDATES = [fulfillmentKeys.all, orderKeys.all, inventoryKeys.all, alertKeys.all]

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

/** Green tick / red cross next to a scan field (the server checks again). */
function ScanState({ value, expected }: { value: string; expected: string[] }) {
  if (!value.trim()) return null
  const ok = expected.includes(value.trim().toUpperCase())
  return ok ? (
    <span className="flex items-center gap-1 text-xs text-emerald-700">
      <CheckCircle2 size={14} aria-hidden="true" /> matches
    </span>
  ) : (
    <span className="flex items-center gap-1 text-xs text-red-700">
      <XCircle size={14} aria-hidden="true" /> does not match this task
    </span>
  )
}

function Footer({
  onClose,
  loading,
  label,
  onSubmit,
}: {
  onClose: () => void
  loading: boolean
  label: string
  onSubmit: () => void
}): ReactNode {
  return (
    <>
      <Button variant="secondary" onClick={onClose} disabled={loading}>
        Cancel
      </Button>
      <Button loading={loading} onClick={onSubmit}>
        {label}
      </Button>
    </>
  )
}

// =============================================================================== pick
export function PickDialog({ task, onClose }: { task: PickingTask | null; onClose: () => void }) {
  return task ? <PickForm task={task} onClose={onClose} /> : null
}

function PickForm({ task, onClose }: { task: PickingTask; onClose: () => void }) {
  const [binCode, setBinCode] = useState('')
  const [productCode, setProductCode] = useState('')
  const [quantity, setQuantity] = useState(String(task.quantity))
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const picked = /^\d+$/.test(quantity.trim()) ? Number(quantity) : NaN
  const short = Number.isInteger(picked) && picked < task.quantity

  const complete = useApiMutation(
    () =>
      completePicking(task.id, {
        bin_code: binCode,
        product_code: productCode,
        quantity_picked: picked,
        short_reason: short ? reason.trim() : undefined,
      }),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: (t) =>
        t.status === 'short'
          ? `Short pick recorded (${t.quantity_picked} of ${t.quantity}); a cycle count was opened`
          : `Picked ${t.quantity_picked} × ${t.product.sku}`,
      onSuccess: onClose,
    },
  )

  const submit = () => {
    if (!binCode.trim() || !productCode.trim()) return setError('Scan the bin and the product')
    if (!Number.isInteger(picked) || picked > task.quantity)
      return setError(`Enter how many you picked (0 to ${task.quantity})`)
    if (short && reason.trim().length < 3) return setError('Say why units are missing')
    setError(null)
    complete.mutate(undefined)
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Pick ${task.quantity} × ${task.product.sku}`}
      description={`Order ${task.order.order_number} · stop ${task.sequence} of the route`}
      dismissible={!complete.isPending}
      footer={
        <Footer
          onClose={onClose}
          loading={complete.isPending}
          label="Confirm pick"
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg bg-slate-50 p-3 text-sm">
          <p>
            Go to <span className="font-mono font-semibold">{task.bin.location_code}</span>
          </p>
          <p className="text-slate-600">
            Take {task.quantity} × {task.product.name} ({task.product.sku})
          </p>
        </div>
        <div>
          <TextField
            label="Scan the bin"
            value={binCode}
            autoComplete="off"
            onChange={(event) => setBinCode(event.target.value)}
            data-autofocus
          />
          <ScanState value={binCode} expected={[task.bin.location_code]} />
        </div>
        <div>
          <TextField
            label="Scan the product"
            value={productCode}
            autoComplete="off"
            hint="SKU or barcode"
            onChange={(event) => setProductCode(event.target.value)}
          />
          <ScanState
            value={productCode}
            expected={[task.product.sku, ...(task.product.barcode ? [task.product.barcode] : [])]}
          />
        </div>
        <TextField
          label="Quantity picked"
          inputMode="numeric"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          hint={`Expected ${task.quantity}`}
        />
        {short && (
          <TextField
            label="Why are units missing?"
            required
            value={reason}
            maxLength={200}
            onChange={(event) => setReason(event.target.value)}
            hint="The missing units are written off and the bin is counted again."
          />
        )}
        <Problem message={error ?? complete.errorMessage} />
      </div>
    </Modal>
  )
}

// =============================================================================== pack
export function PackDialog({
  task,
  onClose,
  onPacked,
}: {
  task: PackingTask | null
  onClose: () => void
  onPacked: (task: PackingTask) => void
}) {
  return task ? <PackForm task={task} onClose={onClose} onPacked={onPacked} /> : null
}

function PackForm({
  task,
  onClose,
  onPacked,
}: {
  task: PackingTask
  onClose: () => void
  onPacked: (task: PackingTask) => void
}) {
  // The packer counts; nothing is pre-filled so the count is a real check.
  const [counts, setCounts] = useState<Record<number, string>>({})
  const [parcels, setParcels] = useState('1')
  const [weight, setWeight] = useState('')
  const [error, setError] = useState<string | null>(null)

  const complete = useApiMutation(
    () =>
      completePacking(task.id, {
        items: task.lines.map((l) => ({
          product_id: l.product.id,
          quantity: Number(counts[l.product.id]),
        })),
        package_count: Number(parcels),
        weight_kg: weight.trim().replace(',', '.'),
      }),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: `Order ${task.order.order_number} packed`,
      onSuccess: onPacked,
    },
  )

  const submit = () => {
    const missing = task.lines.find((l) => !/^\d+$/.test((counts[l.product.id] ?? '').trim()))
    if (missing) return setError(`Count ${missing.product.sku}`)
    if (!/^\d+$/.test(parcels) || Number(parcels) < 1) return setError('At least 1 parcel')
    if (!/^\d+([.,]\d{1,3})?$/.test(weight.trim()) || Number(weight.replace(',', '.')) <= 0)
      return setError('Enter the total weight in kg, e.g. 4.5')
    setError(null)
    complete.mutate(undefined)
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Pack order ${task.order.order_number}`}
      description="Count every item into the parcels, then weigh them."
      size="lg"
      dismissible={!complete.isPending}
      footer={
        <Footer onClose={onClose} loading={complete.isPending} label="Packed" onSubmit={submit} />
      }
    >
      <div className="space-y-4">
        <table className="w-full text-sm">
          <caption className="sr-only">Items to pack</caption>
          <thead className="text-left text-xs text-slate-500 uppercase">
            <tr>
              <th className="py-2">Product</th>
              <th className="py-2 text-right">Picked</th>
              <th className="py-2 text-right">Counted</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {task.lines.map((line) => {
              const value = counts[line.product.id] ?? ''
              const wrong = value !== '' && Number(value) !== line.quantity_picked
              return (
                <tr key={line.product.id}>
                  <td className="py-2">
                    <p className="font-mono text-xs">{line.product.sku}</p>
                    <p>{line.product.name}</p>
                    {line.quantity_picked < line.quantity_ordered && (
                      <p className="text-xs text-amber-700">
                        {line.quantity_ordered - line.quantity_picked} short of the order
                      </p>
                    )}
                  </td>
                  <td className="py-2 text-right">{line.quantity_picked}</td>
                  <td className="py-2 text-right">
                    <input
                      aria-label={`Counted ${line.product.sku}`}
                      inputMode="numeric"
                      value={value}
                      onChange={(event) =>
                        setCounts((all) => ({ ...all, [line.product.id]: event.target.value }))
                      }
                      className={`w-20 rounded-lg border px-2 py-1 text-right ${wrong ? 'border-red-400' : 'border-slate-300'}`}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Parcels"
            inputMode="numeric"
            value={parcels}
            onChange={(event) => setParcels(event.target.value)}
          />
          <TextField
            label="Total weight (kg)"
            inputMode="decimal"
            value={weight}
            onChange={(event) => setWeight(event.target.value)}
          />
        </div>
        <Problem message={error ?? complete.errorMessage} />
      </div>
    </Modal>
  )
}

// =============================================================================== ship
export function ShipDialog({
  order,
  onClose,
}: {
  order: { id: number; order_number: string } | null
  onClose: () => void
}) {
  return order ? <ShipForm order={order} onClose={onClose} /> : null
}

function ShipForm({
  order,
  onClose,
}: {
  order: { id: number; order_number: string }
  onClose: () => void
}) {
  const carriers = useApiQuery(fulfillmentKeys.carriers, listCarriers)
  const [carrierId, setCarrierId] = useState('')
  const [tracking, setTracking] = useState('')
  const [expected, setExpected] = useState('')
  const [error, setError] = useState<string | null>(null)

  const ship = useApiMutation(
    () =>
      createShipment({
        order_id: order.id,
        carrier_id: Number(carrierId),
        tracking_number: tracking.trim() || undefined,
        expected_delivery_date: expected || undefined,
      }),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: (s) => `Shipped with ${s.carrier.code} ${s.tracking_number}`,
      onSuccess: onClose,
    },
  )

  const submit = () => {
    if (!carrierId) return setError('Choose a carrier')
    setError(null)
    ship.mutate(undefined)
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Ship order ${order.order_number}`}
      description="Hand the parcels to a carrier."
      dismissible={!ship.isPending}
      footer={<Footer onClose={onClose} loading={ship.isPending} label="Ship" onSubmit={submit} />}
    >
      <div className="space-y-4">
        <SelectField
          label="Carrier"
          required
          value={carrierId}
          placeholder="Choose a carrier"
          onChange={(event) => setCarrierId(event.target.value)}
          options={(carriers.data ?? []).map((c) => ({
            value: c.id,
            label: `${c.name} (${c.default_transit_days} working day${c.default_transit_days === 1 ? '' : 's'})`,
          }))}
        />
        <TextField
          label="Tracking number"
          value={tracking}
          maxLength={40}
          onChange={(event) => setTracking(event.target.value)}
          hint="Leave empty to generate one"
        />
        <TextField
          label="Expected delivery"
          type="date"
          value={expected}
          onChange={(event) => setExpected(event.target.value)}
          hint="Leave empty for the carrier's usual delivery time"
        />
        <Problem message={error ?? ship.errorMessage} />
      </div>
    </Modal>
  )
}
