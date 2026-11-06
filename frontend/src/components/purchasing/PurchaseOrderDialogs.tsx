import { AlertCircle, PackageCheck, Send, Trash2, XCircle } from 'lucide-react'
import { useState } from 'react'

import { alertKeys } from '../../api/alertsApi'
import { catalogKeys, listSuppliers } from '../../api/catalogApi'
import { inventoryKeys } from '../../api/inventoryApi'
import { orderKeys } from '../../api/ordersApi'
import {
  createPurchaseOrder,
  purchaseOrderAction,
  purchaseOrderKeys,
  receivePurchaseOrder,
} from '../../api/purchasingApi'
import { listWarehouses, warehouseKeys } from '../../api/warehouseApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { ProductRef } from '../../types/inventory'
import type { PurchaseOrder, PurchaseOrderItem } from '../../types/purchasing'
import type { BinDetail } from '../../types/warehouse'
import { formatMoney } from '../../utils/format'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { DetailItem } from '../common/PageHeader'
import { SelectField, TextAreaField, TextField } from '../form/fields'
import { formatDateTime } from '../inventory/movementFormat'
import { BinCodeField, ProductPicker } from '../inventory/Pickers'
import { formatDate } from '../orders/orderFormat'
import { PO_STATUS_LABELS, PO_TONES } from './purchasingFormat'

const INVALIDATES = [purchaseOrderKeys.all, inventoryKeys.all, orderKeys.all, alertKeys.all]

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

const WHOLE = /^\d+$/
const MONEY = /^\d+(\.\d{1,2})?$/

// ========================================================================== new PO
interface DraftLine {
  product: ProductRef
  quantity: string
  unitCost: string // empty: the supplier's price
}

export function NewPurchaseOrderDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (po: PurchaseOrder) => void
}) {
  return open ? <NewPurchaseOrderForm onClose={onClose} onCreated={onCreated} /> : null
}

function NewPurchaseOrderForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (po: PurchaseOrder) => void
}) {
  const [supplierId, setSupplierId] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [lines, setLines] = useState<DraftLine[]>([])
  const [expected, setExpected] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const suppliers = useApiQuery([...catalogKeys.suppliers, 'active'], () =>
    listSuppliers({ status: 'active', limit: 100, sort: 'name' }),
  )
  const warehouses = useApiQuery(warehouseKeys.all, listWarehouses)
  const activeWarehouses = (warehouses.data ?? []).filter((w) => w.is_active)
  const chosenWarehouse =
    warehouseId || (activeWarehouses.length === 1 ? activeWarehouses[0].id : '')

  const create = useApiMutation(createPurchaseOrder, {
    invalidates: [purchaseOrderKeys.all],
    toastOnError: false,
    successMessage: (po) => `Purchase order ${po.po_number} drafted`,
    onSuccess: onCreated,
  })

  const update = (index: number, change: Partial<DraftLine>) =>
    setLines((all) => all.map((l, i) => (i === index ? { ...l, ...change } : l)))

  const submit = () => {
    if (!supplierId) return setError('Choose a supplier')
    if (!chosenWarehouse) return setError('Choose a warehouse')
    if (lines.length === 0) return setError('Add at least one product')
    for (const l of lines) {
      if (!WHOLE.test(l.quantity.trim()) || Number(l.quantity) < 1)
        return setError(`${l.product.sku}: enter a whole quantity of at least 1`)
      if (l.unitCost.trim() && !MONEY.test(l.unitCost.trim()))
        return setError(`${l.product.sku}: enter a price like 12.50, or leave it empty`)
    }
    setError(null)
    create.mutate({
      supplier_id: Number(supplierId),
      warehouse_id: Number(chosenWarehouse),
      expected_date: expected || undefined,
      notes: notes.trim() || undefined,
      items: lines.map((l) => ({
        product_id: l.product.id,
        quantity: Number(l.quantity),
        unit_cost: l.unitCost.trim() || undefined,
      })),
    })
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="New purchase order"
      description="Prices and the expected date come from the supplier's offers unless you enter them."
      size="lg"
      dismissible={!create.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button loading={create.isPending} onClick={submit}>
            Save draft
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="Supplier"
            required
            value={supplierId}
            placeholder="Choose a supplier"
            onChange={(event) => setSupplierId(event.target.value)}
            options={(suppliers.data?.items ?? []).map((s) => ({
              value: s.id,
              label: `${s.code} · ${s.name} (${s.lead_time_days} days)`,
            }))}
          />
          <SelectField
            label="Warehouse"
            required
            value={String(chosenWarehouse)}
            placeholder="Choose a warehouse"
            onChange={(event) => setWarehouseId(event.target.value)}
            options={activeWarehouses.map((w) => ({ value: w.id, label: `${w.code} · ${w.name}` }))}
          />
        </div>

        <div className="space-y-2">
          {lines.length > 0 && (
            <ul
              aria-label="Purchase order lines"
              className="divide-y divide-slate-100 rounded-lg border border-slate-200"
            >
              {lines.map((line, index) => (
                <li key={line.product.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs">{line.product.sku}</p>
                    <p className="truncate text-sm">{line.product.name}</p>
                  </div>
                  <input
                    aria-label={`Quantity of ${line.product.sku}`}
                    inputMode="numeric"
                    value={line.quantity}
                    onChange={(event) => update(index, { quantity: event.target.value })}
                    className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm"
                  />
                  <input
                    aria-label={`Unit cost of ${line.product.sku}`}
                    inputMode="decimal"
                    placeholder="supplier price"
                    value={line.unitCost}
                    onChange={(event) => update(index, { unitCost: event.target.value })}
                    className="w-32 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm"
                  />
                  <button
                    type="button"
                    aria-label={`Remove ${line.product.sku}`}
                    onClick={() => setLines((all) => all.filter((_, i) => i !== index))}
                    className="rounded p-1 text-slate-500 hover:bg-slate-100"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <ProductPicker
            value={null}
            onChange={(product) => {
              if (product && !lines.some((l) => l.product.id === product.id)) {
                setLines((all) => [...all, { product, quantity: '1', unitCost: '' }])
              }
            }}
          />
        </div>

        <TextField
          label="Expected delivery"
          type="date"
          value={expected}
          hint="Leave empty to use the supplier's lead time"
          onChange={(event) => setExpected(event.target.value)}
        />
        <TextAreaField
          label="Notes"
          value={notes}
          maxLength={500}
          onChange={(event) => setNotes(event.target.value)}
        />
        <Problem
          message={
            error ?? create.errorMessage ?? suppliers.errorMessage ?? warehouses.errorMessage
          }
        />
      </div>
    </Modal>
  )
}

// ======================================================================= PO detail
export function PurchaseOrderDialog({
  po,
  canManage,
  onClose,
}: {
  po: PurchaseOrder | null
  canManage: boolean
  onClose: () => void
}) {
  return po ? (
    <PurchaseOrderView key={po.id} po={po} canManage={canManage} onClose={onClose} />
  ) : null
}

function PurchaseOrderView({
  po: initial,
  canManage,
  onClose,
}: {
  po: PurchaseOrder
  canManage: boolean
  onClose: () => void
}) {
  const [po, setPo] = useState(initial)
  const [receiving, setReceiving] = useState(false)
  const action = useApiMutation((name: 'order' | 'cancel') => purchaseOrderAction(po.id, name), {
    invalidates: INVALIDATES,
    successMessage: (p) =>
      p.status === 'cancelled'
        ? `Purchase order ${p.po_number} cancelled`
        : `Purchase order ${p.po_number} sent to ${p.supplier.name}`,
    onSuccess: setPo,
  })
  const open = po.status === 'ordered' || po.status === 'partially_received'

  if (receiving) {
    return (
      <ReceiveForm
        po={po}
        onBack={() => setReceiving(false)}
        onReceived={(next) => {
          setPo(next)
          setReceiving(false)
        }}
      />
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Purchase order ${po.po_number}`}
      description={`${po.supplier.name} → ${po.warehouse.code}`}
      size="lg"
      footer={
        <>
          {canManage && (po.status === 'draft' || po.status === 'ordered') && (
            <Button
              variant="ghost"
              icon={<XCircle size={16} aria-hidden="true" />}
              loading={action.isPending && action.variables === 'cancel'}
              disabled={action.isPending}
              onClick={() => action.mutate('cancel')}
            >
              Cancel order
            </Button>
          )}
          {canManage && po.status === 'draft' && (
            <Button
              icon={<Send size={16} aria-hidden="true" />}
              loading={action.isPending && action.variables === 'order'}
              disabled={action.isPending}
              onClick={() => action.mutate('order')}
            >
              Send to supplier
            </Button>
          )}
          {open && (
            <Button
              icon={<PackageCheck size={16} aria-hidden="true" />}
              onClick={() => setReceiving(true)}
            >
              Receive goods
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <dl className="grid gap-3 sm:grid-cols-3">
          <DetailItem label="Status">
            <span className="flex flex-wrap gap-1">
              <Badge tone={PO_TONES[po.status]}>{PO_STATUS_LABELS[po.status]}</Badge>
              {po.is_overdue && <Badge tone="danger">overdue</Badge>}
            </span>
          </DetailItem>
          <DetailItem label="Expected">{formatDate(po.expected_date)}</DetailItem>
          <DetailItem label="Total">{formatMoney(po.total_cost)}</DetailItem>
          <DetailItem label="Created">
            {formatDateTime(po.created_at)}
            {po.created_by && ` · ${po.created_by.full_name}`}
          </DetailItem>
          <DetailItem label="Ordered">
            {po.ordered_at ? formatDateTime(po.ordered_at) : '—'}
          </DetailItem>
          <DetailItem label="Received">
            {po.received_at ? formatDateTime(po.received_at) : '—'}
          </DetailItem>
        </dl>
        {po.notes && <p className="text-sm text-slate-600">{po.notes}</p>}
        <table className="w-full text-sm">
          <caption className="sr-only">Lines of {po.po_number}</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="py-2 font-medium">Product</th>
              <th className="py-2 text-right font-medium">Ordered</th>
              <th className="py-2 text-right font-medium">Received</th>
              <th className="py-2 text-right font-medium">Unit cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {po.items.map((item) => (
              <tr key={item.id}>
                <td className="py-2">
                  <span className="font-mono text-xs">{item.product.sku}</span> {item.product.name}
                </td>
                <td className="py-2 text-right">{item.quantity}</td>
                <td className="py-2 text-right">{item.quantity_received}</td>
                <td className="py-2 text-right">{formatMoney(item.unit_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Problem message={action.errorMessage} />
      </div>
    </Modal>
  )
}

// ========================================================================= receive
interface ReceiveLine {
  quantity: string
  bin: BinDetail | null
}

function ReceiveForm({
  po,
  onBack,
  onReceived,
}: {
  po: PurchaseOrder
  onBack: () => void
  onReceived: (po: PurchaseOrder) => void
}) {
  const outstanding = po.items.filter((i) => i.quantity_outstanding > 0)
  const [lines, setLines] = useState<Record<number, ReceiveLine>>(() =>
    Object.fromEntries(
      outstanding.map((i) => [
        i.product.id,
        { quantity: String(i.quantity_outstanding), bin: null },
      ]),
    ),
  )
  const [error, setError] = useState<string | null>(null)

  const receive = useApiMutation(
    (items: { product_id: number; quantity: number; bin_id: number }[]) =>
      receivePurchaseOrder(po.id, items),
    {
      invalidates: INVALIDATES,
      toastOnError: false,
      successMessage: (p) =>
        p.status === 'received'
          ? `${p.po_number} fully received — stock updated`
          : `${p.po_number} partly received — stock updated`,
      onSuccess: onReceived,
    },
  )

  const update = (item: PurchaseOrderItem, change: Partial<ReceiveLine>) =>
    setLines((all) => ({ ...all, [item.product.id]: { ...all[item.product.id], ...change } }))

  const submit = () => {
    const items = []
    for (const item of outstanding) {
      const line = lines[item.product.id]
      const text = line.quantity.trim()
      if (text === '' || text === '0') continue // not arrived (yet)
      if (!WHOLE.test(text)) return setError(`${item.product.sku}: enter a whole number`)
      if (Number(text) > item.quantity_outstanding)
        return setError(`${item.product.sku}: only ${item.quantity_outstanding} outstanding`)
      if (!line.bin) return setError(`${item.product.sku}: choose the bin it goes into`)
      if (line.bin.warehouse.id !== po.warehouse.id)
        return setError(`${item.product.sku}: the bin must be in ${po.warehouse.code}`)
      items.push({ product_id: item.product.id, quantity: Number(text), bin_id: line.bin.id })
    }
    if (items.length === 0) return setError('Enter the quantity of at least one product')
    setError(null)
    receive.mutate(items)
  }

  return (
    <Modal
      open
      onClose={onBack}
      title={`Receive ${po.po_number}`}
      description={`Goods from ${po.supplier.name}. Leave a quantity at 0 if it has not arrived.`}
      size="lg"
      dismissible={!receive.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onBack} disabled={receive.isPending}>
            Back
          </Button>
          <Button loading={receive.isPending} onClick={submit}>
            Book into stock
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {outstanding.map((item) => (
          <div key={item.id} className="space-y-2 rounded-lg border border-slate-200 p-3">
            <p className="text-sm">
              <span className="font-mono text-xs">{item.product.sku}</span> {item.product.name}{' '}
              <span className="text-slate-500">
                · {item.quantity_outstanding} of {item.quantity} outstanding
              </span>
            </p>
            <div className="grid gap-3 sm:grid-cols-[11rem_1fr]">
              <TextField
                label={`Received ${item.product.sku}`}
                inputMode="numeric"
                value={lines[item.product.id].quantity}
                onChange={(event) => update(item, { quantity: event.target.value })}
              />
              <BinCodeField
                label={`Bin for ${item.product.sku}`}
                value={lines[item.product.id].bin}
                onChange={(bin) => update(item, { bin })}
              />
            </div>
          </div>
        ))}
        <p className="text-xs text-slate-500">
          The bin's weight and volume limits are checked; waiting backorders are filled
          automatically.
        </p>
        <Problem message={error ?? receive.errorMessage} />
      </div>
    </Modal>
  )
}
