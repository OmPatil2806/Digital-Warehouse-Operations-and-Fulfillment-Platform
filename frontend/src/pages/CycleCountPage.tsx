import { ArrowLeft, Check, Plus, Save, Send, Undo2, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { getErrorMessage } from '../api/apiClient'
import { cycleCountAction, getCycleCount, inventoryKeys, recordCounts } from '../api/inventoryApi'
import { warehouseKeys } from '../api/warehouseApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { DetailItem, PageHeader } from '../components/common/PageHeader'
import { COUNT_STATUS_TONES, formatDateTime } from '../components/inventory/movementFormat'
import { NoteDialog } from '../components/inventory/NoteDialog'
import { isApprover } from '../components/inventory/operations'
import { ProductPicker } from '../components/inventory/Pickers'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import type { CycleCount, ProductRef } from '../types/inventory'
import NotFoundPage from './NotFoundPage'

/** A cycle count: enter counted quantities, submit, and (managers) approve or send back. */
export default function CycleCountPage() {
  const id = Number(useParams().countId)
  const count = useApiQuery(inventoryKeys.cycleCount(id), () => getCycleCount(id), {
    enabled: Number.isInteger(id),
  })

  if (!Number.isInteger(id) || (count.error && getErrorMessage(count.error).includes('not found')))
    return <NotFoundPage />
  if (count.isPending)
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading…
      </p>
    )
  if (!count.data)
    return (
      <p role="alert" className="text-sm text-red-700">
        {count.errorMessage}
      </p>
    )
  // Remount the sheet when the status changes, so entered numbers start from the saved ones.
  return <CountSheet key={`${count.data.id}-${count.data.status}`} count={count.data} />
}

function CountSheet({ count }: { count: CycleCount }) {
  const { user } = useAuth()
  const open = count.status === 'open'
  const [entries, setEntries] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      count.lines.map((line) => [line.product.id, line.counted_quantity?.toString() ?? '']),
    ),
  )
  const [extra, setExtra] = useState<ProductRef[]>([])
  const [adding, setAdding] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [rejecting, setRejecting] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  const invalidates = [inventoryKeys.all, warehouseKeys.all]
  const save = useApiMutation(
    (lines: { product_id: number; counted_quantity: number }[]) => recordCounts(count.id, lines),
    { invalidates, successMessage: 'Counts saved', onSuccess: () => setExtra([]) },
  )
  const action = useApiMutation(
    ({ name, note }: { name: 'submit' | 'approve' | 'reject' | 'cancel'; note?: string }) =>
      cycleCountAction(count.id, name, note),
    {
      invalidates,
      successMessage: (c) =>
        ({
          open: 'Sent back for a recount',
          submitted: 'Submitted for approval',
          completed: 'Approved — stock corrected',
          cancelled: 'Count cancelled',
        })[c.status],
      onSuccess: () => {
        setRejecting(false)
        setCancelling(false)
      },
    },
  )

  const lines = [
    ...count.lines.map((line) => ({
      product: line.product,
      expected: line.expected_quantity as number | null,
      saved: line.counted_quantity,
      variance: line.variance,
    })),
    ...extra.map((product) => ({ product, expected: null, saved: null, variance: null })),
  ]

  /** Entered numbers, or an error text if one is not a whole number >= 0. */
  const collect = (requireAll: boolean) => {
    const result: { product_id: number; counted_quantity: number }[] = []
    for (const line of lines) {
      const text = (entries[line.product.id] ?? '').trim()
      if (text === '') {
        if (requireAll) return `Count every product first (${line.product.sku} is missing)`
        continue
      }
      if (!/^\d+$/.test(text)) return `${line.product.sku}: enter a whole number (0 or more)`
      result.push({ product_id: line.product.id, counted_quantity: Number(text) })
    }
    return result
  }

  const onSave = () => {
    const result = collect(false)
    setFormError(typeof result === 'string' ? result : null)
    if (typeof result !== 'string' && result.length) save.mutate(result)
  }

  const onSubmit = async () => {
    const result = collect(true)
    setFormError(typeof result === 'string' ? result : null)
    if (typeof result === 'string') return
    await save.mutateAsync(result)
    action.mutate({ name: 'submit' })
  }

  const approver = isApprover(user)
  const startedByMe = count.requested_by?.id === user?.id
  const canDecide = count.status === 'submitted' && approver && !startedByMe
  const canCancel =
    (count.status === 'open' || count.status === 'submitted') && (startedByMe || approver)

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Link
        to="/inventory?view=counts"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft size={14} aria-hidden="true" /> All cycle counts
      </Link>

      <PageHeader
        title={`Cycle count #${count.id}`}
        description={
          <span className="inline-flex items-center gap-2">
            <span className="font-mono">{count.bin.location_code}</span>
            <Badge tone={COUNT_STATUS_TONES[count.status]}>{count.status}</Badge>
          </span>
        }
        actions={
          canCancel && (
            <Button
              variant="ghost"
              icon={<XCircle size={14} aria-hidden="true" />}
              onClick={() => setCancelling(true)}
            >
              Cancel count
            </Button>
          )
        }
      />

      <dl className="grid gap-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:grid-cols-3">
        <DetailItem label="Started">
          {formatDateTime(count.created_at)} by {count.requested_by?.full_name ?? 'System'}
        </DetailItem>
        <DetailItem label="Submitted">
          {count.submitted_at ? formatDateTime(count.submitted_at) : '—'}
        </DetailItem>
        <DetailItem label="Decision">
          {count.decided_by
            ? `${count.decided_by.full_name}${count.decision_note ? `: ${count.decision_note}` : ''}`
            : '—'}
        </DetailItem>
        {count.note && (
          <div className="sm:col-span-3">
            <DetailItem label="Note">{count.note}</DetailItem>
          </div>
        )}
      </dl>

      {count.status === 'open' && count.decision_note && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Sent back for a recount: {count.decision_note}
        </p>
      )}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <caption className="sr-only">Counted products</caption>
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-3">Product</th>
              <th className="px-4 py-3 text-right">Expected</th>
              <th className="px-4 py-3 text-right">Counted</th>
              <th className="px-4 py-3 text-right">Difference</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {lines.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                  The system expects this bin to be empty. Add any product you find.
                </td>
              </tr>
            )}
            {lines.map((line) => {
              const text = entries[line.product.id] ?? ''
              const typed = /^\d+$/.test(text.trim()) ? Number(text) : null
              const difference =
                open && typed !== null && line.expected !== null
                  ? typed - line.expected
                  : line.variance
              return (
                <tr key={line.product.id}>
                  <td className="px-4 py-3">
                    <p className="font-mono text-xs">{line.product.sku}</p>
                    <p>{line.product.name}</p>
                  </td>
                  <td className="px-4 py-3 text-right">{line.expected ?? 'new'}</td>
                  <td className="px-4 py-3 text-right">
                    {open ? (
                      <input
                        aria-label={`Counted ${line.product.sku}`}
                        inputMode="numeric"
                        value={text}
                        onChange={(event) =>
                          setEntries((current) => ({
                            ...current,
                            [line.product.id]: event.target.value,
                          }))
                        }
                        className="w-24 rounded-lg border border-slate-300 px-2 py-1 text-right"
                      />
                    ) : (
                      (line.saved ?? '—')
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-medium">
                    {difference == null ? (
                      '—'
                    ) : difference === 0 ? (
                      <span className="text-emerald-700">OK</span>
                    ) : (
                      <span className={difference < 0 ? 'text-red-700' : 'text-amber-700'}>
                        {difference > 0 ? `+${difference}` : `−${Math.abs(difference)}`}
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {formError && (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {formError}
        </p>
      )}

      {open && (
        <div className="space-y-4">
          {adding ? (
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <ProductPicker
                value={null}
                onChange={(product) => {
                  if (product && !lines.some((l) => l.product.id === product.id)) {
                    setExtra((current) => [...current, product])
                  }
                  setAdding(false)
                }}
              />
            </div>
          ) : (
            <Button
              variant="secondary"
              icon={<Plus size={14} aria-hidden="true" />}
              onClick={() => setAdding(true)}
            >
              Add a product found here
            </Button>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              icon={<Save size={14} aria-hidden="true" />}
              loading={save.isPending && !action.isPending}
              onClick={onSave}
            >
              Save counts
            </Button>
            <Button
              icon={<Send size={14} aria-hidden="true" />}
              loading={action.isPending}
              onClick={() => void onSubmit()}
            >
              Submit for approval
            </Button>
          </div>
        </div>
      )}

      {count.status === 'submitted' && !canDecide && (
        <p className="text-sm text-slate-500">
          {approver && startedByMe
            ? 'You started this count, so another manager or admin has to approve it.'
            : 'Waiting for a manager to approve the differences.'}
        </p>
      )}
      {canDecide && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="secondary"
            icon={<Undo2 size={14} aria-hidden="true" />}
            onClick={() => setRejecting(true)}
          >
            Send back for recount
          </Button>
          <Button
            icon={<Check size={14} aria-hidden="true" />}
            loading={action.isPending}
            onClick={() => action.mutate({ name: 'approve' })}
          >
            Approve and correct stock
          </Button>
        </div>
      )}

      <NoteDialog
        open={rejecting}
        title="Send back for a recount"
        label="What should be counted again?"
        confirmLabel="Send back"
        loading={action.isPending}
        onCancel={() => setRejecting(false)}
        onConfirm={(note) => action.mutate({ name: 'reject', note })}
      />
      <ConfirmDialog
        open={cancelling}
        title={`Cancel cycle count #${count.id}?`}
        message="Nothing is corrected. The bin can be counted again later."
        confirmLabel="Cancel count"
        tone="danger"
        loading={action.isPending}
        onConfirm={() => action.mutate({ name: 'cancel' })}
        onCancel={() => setCancelling(false)}
      />
    </div>
  )
}
