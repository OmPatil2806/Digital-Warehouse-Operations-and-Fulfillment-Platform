import { AlertCircle, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { getProductStock, inventoryKeys } from '../../api/inventoryApi'
import { createOrder, getMyCustomer, listCustomers, orderKeys } from '../../api/ordersApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import { useAuth } from '../../hooks/useAuth'
import type { ProductRef } from '../../types/inventory'
import { ORDER_PRIORITIES, type OrderPriority } from '../../types/orders'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { SelectField, TextAreaField, TextField } from '../form/fields'
import { ProductPicker } from '../inventory/Pickers'
import { isCustomerOnly } from './orderFormat'

interface Line {
  product: ProductRef
  quantity: string
}

/** Live "available" hint for warehouse users (customers cannot see stock). */
function Availability({ productId, quantity }: { productId: number; quantity: number }) {
  const stock = useApiQuery(inventoryKeys.product(productId), () => getProductStock(productId))
  if (!stock.data) return null
  const available = stock.data.quantity_available
  const short = quantity > available
  return (
    <span className={`text-xs ${short ? 'text-amber-700' : 'text-slate-500'}`}>
      {available} available{short ? ' — the rest will be backordered' : ''}
    </span>
  )
}

export function NewOrderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? <NewOrderForm onClose={onClose} /> : null
}

function NewOrderForm({ onClose }: { onClose: () => void }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const customerOnly = isCustomerOnly(user)
  const [customerId, setCustomerId] = useState('')
  const [lines, setLines] = useState<Line[]>([])
  const [priority, setPriority] = useState<OrderPriority>('normal')
  const [deliveryDate, setDeliveryDate] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const me = useApiQuery(orderKeys.myCustomer, getMyCustomer, { enabled: customerOnly })
  const customers = useApiQuery(orderKeys.customers(''), () => listCustomers(), {
    enabled: !customerOnly,
  })

  const create = useApiMutation(createOrder, {
    invalidates: [orderKeys.all],
    toastOnError: false,
    successMessage: (o) => `Order ${o.order_number} created — confirm it to reserve the stock`,
    onSuccess: (o) => {
      onClose()
      void navigate(`/orders/${o.id}`)
    },
  })

  const submit = () => {
    const chosen = customerOnly ? me.data?.id : Number(customerId) || undefined
    if (!chosen) return setError('Choose a customer')
    if (lines.length === 0) return setError('Add at least one product')
    const bad = lines.find((l) => !/^\d+$/.test(l.quantity.trim()) || Number(l.quantity) < 1)
    if (bad) return setError(`${bad.product.sku}: enter a whole number of at least 1`)
    setError(null)
    create.mutate({
      customer_id: chosen,
      items: lines.map((l) => ({ product_id: l.product.id, quantity: Number(l.quantity) })),
      priority: customerOnly ? undefined : priority,
      requested_delivery_date: deliveryDate || undefined,
      notes: notes.trim() || undefined,
    })
  }

  const message = error ?? create.errorMessage
  return (
    <Modal
      open
      onClose={onClose}
      title="New order"
      description="Prices are taken from the catalog when the order is placed."
      size="lg"
      dismissible={!create.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button loading={create.isPending} onClick={submit}>
            Place order
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {customerOnly ? (
          <p className="text-sm">
            Ordering for{' '}
            <span className="font-medium">
              {me.data ? `${me.data.name} (${me.data.code})` : (me.errorMessage ?? '…')}
            </span>
          </p>
        ) : (
          <SelectField
            label="Customer"
            required
            value={customerId}
            placeholder="Choose a customer"
            onChange={(event) => setCustomerId(event.target.value)}
            options={(customers.data?.items ?? []).map((c) => ({
              value: c.id,
              label: `${c.code} · ${c.name}${c.city ? ` (${c.city})` : ''}`,
            }))}
          />
        )}

        <div className="space-y-2">
          {lines.length > 0 && (
            <ul
              aria-label="Order lines"
              className="divide-y divide-slate-100 rounded-lg border border-slate-200"
            >
              {lines.map((line, index) => (
                <li key={line.product.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-xs">{line.product.sku}</p>
                    <p className="truncate text-sm">{line.product.name}</p>
                    {!customerOnly && /^\d+$/.test(line.quantity) && (
                      <Availability productId={line.product.id} quantity={Number(line.quantity)} />
                    )}
                  </div>
                  <input
                    aria-label={`Quantity of ${line.product.sku}`}
                    inputMode="numeric"
                    value={line.quantity}
                    onChange={(event) =>
                      setLines((all) =>
                        all.map((l, i) =>
                          i === index ? { ...l, quantity: event.target.value } : l,
                        ),
                      )
                    }
                    className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-right text-sm"
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
                setLines((all) => [...all, { product, quantity: '1' }])
              }
            }}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {!customerOnly && (
            <SelectField
              label="Priority"
              value={priority}
              onChange={(event) => setPriority(event.target.value as OrderPriority)}
              options={ORDER_PRIORITIES.map((p) => ({
                value: p,
                label: p[0].toUpperCase() + p.slice(1),
              }))}
            />
          )}
          <TextField
            label="Requested delivery date"
            type="date"
            value={deliveryDate}
            onChange={(event) => setDeliveryDate(event.target.value)}
          />
        </div>
        <TextAreaField
          label="Notes"
          value={notes}
          maxLength={2000}
          onChange={(event) => setNotes(event.target.value)}
        />
        {message && (
          <p
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {message}
          </p>
        )}
      </div>
    </Modal>
  )
}
