import { AlertCircle, Info } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'

import {
  getProductStock,
  inventoryKeys,
  receiveStock,
  submitAdjustment,
  submitTransfer,
} from '../../api/inventoryApi'
import { alertKeys } from '../../api/alertsApi'
import { warehouseKeys } from '../../api/warehouseApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import { useAuth } from '../../hooks/useAuth'
import { ADJUSTMENT_KINDS, type AdjustmentKind, type ProductRef } from '../../types/inventory'
import type { BinDetail } from '../../types/warehouse'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { SelectField, TextField } from '../form/fields'
import {
  adjustmentNeedsApproval,
  isApprover,
  KIND_LABELS,
  maxForKind,
  parseQuantity,
  warehouseCode,
} from './operations'
import { BinCodeField, FitHint, ProductPicker, SourceBinSelect } from './Pickers'

type Errors = Partial<Record<'product' | 'bin' | 'target' | 'quantity' | 'reason', string>>

const INVALIDATES = [inventoryKeys.all, warehouseKeys.all, alertKeys.all]

function ServerError({ message }: { message: string | null }) {
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

function Note({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
      <Info size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

function FormDialog({
  open,
  onClose,
  title,
  description,
  submitLabel,
  loading,
  onSubmit,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  description: string
  submitLabel: string
  loading: boolean
  onSubmit: () => void
  children: ReactNode
}) {
  const formId = `${title.replace(/\s+/g, '-').toLowerCase()}-form`
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSubmit()
  }
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      dismissible={!loading}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button type="submit" form={formId} loading={loading}>
            {submitLabel}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="space-y-4">
        {children}
      </form>
    </Modal>
  )
}

interface DialogProps {
  open: boolean
  onClose: () => void
  /** Start with this product selected (e.g. opened from a stock row). */
  initialProduct?: ProductRef | null
}

// =========================================================================== receive
export function ReceiveDialog(props: DialogProps) {
  // Remount on every opening so the form always starts empty.
  return props.open ? <ReceiveForm {...props} /> : null
}

function ReceiveForm({ open, onClose, initialProduct = null }: DialogProps) {
  const [product, setProduct] = useState<ProductRef | null>(initialProduct)
  const [bin, setBin] = useState<BinDetail | null>(null)
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<Errors>({})

  const receive = useApiMutation(receiveStock, {
    invalidates: INVALIDATES,
    toastOnError: false,
    successMessage: (row) =>
      `Received ${quantity} × ${row.product.sku} into ${row.bin.location_code}`,
    onSuccess: onClose,
  })

  const submit = () => {
    const parsed = parseQuantity(quantity)
    const next: Errors = {
      product: product ? undefined : 'Choose a product',
      bin: bin ? undefined : 'Enter a bin code',
      quantity: typeof parsed === 'string' ? parsed : undefined,
    }
    setErrors(next)
    if (!product || !bin || typeof parsed === 'string') return
    receive.mutate({
      product_id: product.id,
      bin_id: bin.id,
      quantity: parsed,
      reason: reason.trim() || undefined,
    })
  }

  const parsed = parseQuantity(quantity)
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      title="Receive goods"
      description="Goods arrived and are put away into a bin."
      submitLabel="Receive"
      loading={receive.isPending}
      onSubmit={submit}
    >
      <ProductPicker value={product} onChange={setProduct} error={errors.product} />
      <BinCodeField label="Put away into bin" value={bin} onChange={setBin} error={errors.bin} />
      <TextField
        label="Quantity"
        required
        inputMode="numeric"
        value={quantity}
        onChange={(event) => {
          setQuantity(event.target.value)
          setErrors((current) => ({ ...current, quantity: undefined }))
        }}
        error={errors.quantity}
      />
      <FitHint
        binId={bin?.id}
        productId={product?.id}
        quantity={typeof parsed === 'number' ? parsed : 0}
      />
      <TextField
        label="Delivery note / purchase order"
        value={reason}
        maxLength={255}
        onChange={(event) => setReason(event.target.value)}
        hint="Optional, e.g. PO-1001"
      />
      <ServerError message={receive.errorMessage} />
    </FormDialog>
  )
}

// ========================================================================== transfer
export function TransferDialog(props: DialogProps) {
  return props.open ? <TransferForm {...props} /> : null
}

function TransferForm({ open, onClose, initialProduct = null }: DialogProps) {
  const { user } = useAuth()
  const [product, setProduct] = useState<ProductRef | null>(initialProduct)
  const [fromBinId, setFromBinId] = useState<number | null>(null)
  const [target, setTarget] = useState<BinDetail | null>(null)
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<Errors>({})

  const stock = useApiQuery(
    inventoryKeys.product(product?.id ?? 0),
    () => getProductStock(product?.id ?? 0),
    { enabled: product !== null },
  )
  const source = stock.data?.bins.find((row) => row.bin.id === fromBinId)
  const crossesWarehouses =
    source !== undefined &&
    target !== null &&
    warehouseCode(source.bin.location_code) !== target.warehouse.code

  const transfer = useApiMutation(submitTransfer, {
    invalidates: INVALIDATES,
    toastOnError: false,
    successMessage: ({ applied, transfer: t }) =>
      applied
        ? `Moved ${t.quantity} × ${t.product.sku} to ${t.to_bin.location_code}`
        : `Transfer request #${t.id} sent to a manager for approval`,
    onSuccess: onClose,
  })

  const submit = () => {
    const parsed = parseQuantity(quantity, source?.quantity_available)
    const next: Errors = {
      product: product ? undefined : 'Choose a product',
      bin: fromBinId ? undefined : 'Choose the bin to move from',
      target: !target
        ? 'Enter the bin to move to'
        : target.id === fromBinId
          ? 'Choose a different bin'
          : undefined,
      quantity: typeof parsed === 'string' ? parsed : undefined,
    }
    setErrors(next)
    if (Object.values(next).some(Boolean) || !product || !fromBinId || !target) return
    transfer.mutate({
      product_id: product.id,
      from_bin_id: fromBinId,
      to_bin_id: target.id,
      quantity: parsed as number,
      reason: reason.trim() || undefined,
    })
  }

  const parsed = parseQuantity(quantity)
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      title="Move stock"
      description="Move available units to another bin. Reserved and damaged units stay."
      submitLabel={crossesWarehouses && !isApprover(user) ? 'Request transfer' : 'Move'}
      loading={transfer.isPending}
      onSubmit={submit}
    >
      <ProductPicker
        value={product}
        onChange={(p) => {
          setProduct(p)
          setFromBinId(null)
        }}
        error={errors.product}
      />
      {product && (
        <SourceBinSelect
          label="From bin"
          rows={stock.data?.bins.filter((row) => row.quantity_available > 0)}
          value={fromBinId}
          onChange={setFromBinId}
          describe={(row) => `${row.quantity_available} available`}
          error={errors.bin}
        />
      )}
      <BinCodeField label="To bin" value={target} onChange={setTarget} error={errors.target} />
      <TextField
        label="Quantity"
        required
        inputMode="numeric"
        value={quantity}
        onChange={(event) => {
          setQuantity(event.target.value)
          setErrors((current) => ({ ...current, quantity: undefined }))
        }}
        error={errors.quantity}
        hint={source ? `At most ${source.quantity_available}` : undefined}
      />
      {target && target.id !== fromBinId && (
        <FitHint
          binId={target.id}
          productId={product?.id}
          quantity={typeof parsed === 'number' ? parsed : 0}
        />
      )}
      {crossesWarehouses && !isApprover(user) && (
        <Note>
          This moves stock to another warehouse ({target.warehouse.code}). A manager has to approve
          it before anything moves.
        </Note>
      )}
      <TextField
        label="Reason"
        value={reason}
        maxLength={255}
        onChange={(event) => setReason(event.target.value)}
        hint="Optional, e.g. Replenish picking bin"
      />
      <ServerError message={transfer.errorMessage} />
    </FormDialog>
  )
}

// ======================================================================== adjustment
export function AdjustDialog(props: DialogProps) {
  return props.open ? <AdjustForm {...props} /> : null
}

function AdjustForm({ open, onClose, initialProduct = null }: DialogProps) {
  const { user } = useAuth()
  const [kind, setKind] = useState<AdjustmentKind>('decrease')
  const [product, setProduct] = useState<ProductRef | null>(initialProduct)
  const [binId, setBinId] = useState<number | null>(null)
  const [foundIn, setFoundIn] = useState<BinDetail | null>(null)
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState<Errors>({})

  const stock = useApiQuery(
    inventoryKeys.product(product?.id ?? 0),
    () => getProductStock(product?.id ?? 0),
    { enabled: product !== null && kind !== 'increase' },
  )
  const row = stock.data?.bins.find((r) => r.bin.id === binId)
  const max = maxForKind(kind, row)
  const needsApproval = adjustmentNeedsApproval(user, kind)
  const usesDamaged = kind === 'restore' || kind === 'write_off'

  const adjust = useApiMutation(submitAdjustment, {
    invalidates: INVALIDATES,
    toastOnError: false,
    successMessage: ({ applied, adjustment: a }) =>
      applied
        ? `Adjustment saved: ${a.quantity} × ${a.product.sku} in ${a.bin.location_code}`
        : `Adjustment request #${a.id} sent to a manager for approval`,
    onSuccess: onClose,
  })

  const submit = () => {
    const parsed = parseQuantity(quantity, max)
    const chosenBin = kind === 'increase' ? foundIn?.id : binId
    const next: Errors = {
      product: product ? undefined : 'Choose a product',
      bin: chosenBin ? undefined : 'Choose a bin',
      quantity: typeof parsed === 'string' ? parsed : undefined,
      reason:
        reason.trim().length >= 3 ? undefined : 'Explain the correction (at least 3 characters)',
    }
    setErrors(next)
    if (Object.values(next).some(Boolean) || !product || !chosenBin) return
    adjust.mutate({
      product_id: product.id,
      bin_id: chosenBin,
      kind,
      quantity: parsed as number,
      reason: reason.trim(),
    })
  }

  const parsed = parseQuantity(quantity)
  return (
    <FormDialog
      open={open}
      onClose={onClose}
      title="Adjust stock"
      description="Correct the stock of a product in one bin. Every correction needs a reason."
      submitLabel={needsApproval ? 'Request approval' : 'Save adjustment'}
      loading={adjust.isPending}
      onSubmit={submit}
    >
      <SelectField
        label="What happened?"
        required
        value={kind}
        onChange={(event) => {
          setKind(event.target.value as AdjustmentKind)
          setErrors({})
        }}
        options={ADJUSTMENT_KINDS.map((k) => ({ value: k, label: KIND_LABELS[k] }))}
      />
      <ProductPicker
        value={product}
        onChange={(p) => {
          setProduct(p)
          setBinId(null)
        }}
        error={errors.product}
      />
      {kind === 'increase' ? (
        <BinCodeField
          label="Found in bin"
          value={foundIn}
          onChange={setFoundIn}
          error={errors.bin}
        />
      ) : (
        product && (
          <SourceBinSelect
            label="Bin"
            rows={stock.data?.bins.filter((r) =>
              usesDamaged ? r.quantity_damaged > 0 : r.quantity_available > 0,
            )}
            value={binId}
            onChange={setBinId}
            describe={(r) =>
              usesDamaged ? `${r.quantity_damaged} damaged` : `${r.quantity_available} available`
            }
            error={errors.bin}
          />
        )
      )}
      <TextField
        label="Quantity"
        required
        inputMode="numeric"
        value={quantity}
        onChange={(event) => {
          setQuantity(event.target.value)
          setErrors((current) => ({ ...current, quantity: undefined }))
        }}
        error={errors.quantity}
        hint={max != null ? `At most ${max}` : undefined}
      />
      {kind === 'increase' && (
        <FitHint
          binId={foundIn?.id}
          productId={product?.id}
          quantity={typeof parsed === 'number' ? parsed : 0}
        />
      )}
      <TextField
        label="Reason"
        required
        value={reason}
        maxLength={255}
        onChange={(event) => {
          setReason(event.target.value)
          setErrors((current) => ({ ...current, reason: undefined }))
        }}
        error={errors.reason}
        hint="e.g. Dropped carton, found during picking"
      />
      {needsApproval && (
        <Note>
          Removing or damaging stock needs a manager&apos;s approval. Your request is checked now
          and applied when a manager approves it.
        </Note>
      )}
      <ServerError message={adjust.errorMessage} />
    </FormDialog>
  )
}
