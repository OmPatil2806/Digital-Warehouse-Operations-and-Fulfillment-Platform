import { Check, X } from 'lucide-react'
import { useState } from 'react'

import {
  decideRequest,
  getApprovalQueue,
  inventoryKeys,
  listMyRequests,
  type RequestKind,
} from '../../api/inventoryApi'
import { alertKeys } from '../../api/alertsApi'
import { warehouseKeys } from '../../api/warehouseApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import { useAuth } from '../../hooks/useAuth'
import type { DocumentStatus, StockAdjustment, StockTransfer } from '../../types/inventory'
import { Badge, type BadgeTone } from '../common/Badge'
import { Button } from '../common/Button'
import { DataTable, type Column } from '../common/DataTable'
import { formatDateTime } from './movementFormat'
import { NoteDialog } from './NoteDialog'
import { isApprover, KIND_LABELS } from './operations'

/** One row per request, whether it is an adjustment or a transfer. */
interface RequestRow {
  key: string
  kind: RequestKind
  id: number
  createdAt: string
  status: DocumentStatus
  what: string
  where: string
  reason: string | null
  requestedBy: string
  requestedById: number | null
  decisionNote: string | null
}

const STATUS_TONES: Record<DocumentStatus, BadgeTone> = {
  pending: 'warning',
  completed: 'success',
  rejected: 'danger',
  cancelled: 'neutral',
}

function toRows(adjustments: StockAdjustment[], transfers: StockTransfer[]): RequestRow[] {
  const rows: RequestRow[] = [
    ...adjustments.map((a) => ({
      key: `adjustments-${a.id}`,
      kind: 'adjustments' as const,
      id: a.id,
      createdAt: a.created_at,
      status: a.status,
      what: `${KIND_LABELS[a.kind]}: ${a.quantity} × ${a.product.sku}`,
      where: a.bin.location_code,
      reason: a.reason,
      requestedBy: a.requested_by?.full_name ?? 'System',
      requestedById: a.requested_by?.id ?? null,
      decisionNote: a.decision_note,
    })),
    ...transfers.map((t) => ({
      key: `transfers-${t.id}`,
      kind: 'transfers' as const,
      id: t.id,
      createdAt: t.created_at,
      status: t.status,
      what: `Transfer: ${t.quantity} × ${t.product.sku}`,
      where: `${t.from_bin.location_code} → ${t.to_bin.location_code}`,
      reason: t.reason,
      requestedBy: t.requested_by?.full_name ?? 'System',
      requestedById: t.requested_by?.id ?? null,
      decisionNote: t.decision_note,
    })),
  ]
  return rows.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}

/**
 * Managers and admins: the approval queue (approve / reject).
 * Staff: their own requests with their status (cancel while pending).
 */
export function RequestsPanel() {
  const { user } = useAuth()
  const approver = isApprover(user)
  const [rejecting, setRejecting] = useState<RequestRow | null>(null)

  const queue = useApiQuery([...inventoryKeys.requests, 'queue'], getApprovalQueue, {
    enabled: approver,
  })
  const mine = useApiQuery([...inventoryKeys.requests, 'mine'], listMyRequests, {
    enabled: !approver,
  })
  const source = approver ? queue : mine
  const rows = source.data ? toRows(source.data.adjustments, source.data.transfers) : undefined

  const decide = useApiMutation(
    ({
      row,
      action,
      note,
    }: {
      row: RequestRow
      action: 'approve' | 'reject' | 'cancel'
      note?: string
    }) => decideRequest(row.kind, row.id, action, note).then((r) => ({ ...r, kind: row.kind })),
    {
      invalidates: [inventoryKeys.all, warehouseKeys.all, alertKeys.all],
      successMessage: (r) =>
        `${r.kind === 'adjustments' ? 'Adjustment' : 'Transfer'} #${r.id} ${r.status === 'completed' ? 'approved and applied' : r.status}`,
      onSuccess: () => setRejecting(null),
    },
  )

  const columns: Column<RequestRow>[] = [
    {
      key: 'when',
      header: 'Requested',
      cell: (r) => (
        <div className="whitespace-nowrap">
          <p>{formatDateTime(r.createdAt)}</p>
          {approver && <p className="text-xs text-slate-500">by {r.requestedBy}</p>}
        </div>
      ),
    },
    {
      key: 'what',
      header: 'Request',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.what}</p>
          <p className="font-mono text-xs text-slate-500">{r.where}</p>
        </div>
      ),
    },
    {
      key: 'reason',
      header: 'Reason',
      cell: (r) => (
        <div className="text-xs">
          <p>{r.reason ?? '—'}</p>
          {r.decisionNote && <p className="text-slate-500">Manager: {r.decisionNote}</p>}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (r) => <Badge tone={STATUS_TONES[r.status]}>{r.status}</Badge>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (r) =>
        r.status !== 'pending' ? null : approver ? (
          <div className="flex justify-end gap-1">
            <Button
              size="sm"
              icon={<Check size={14} aria-hidden="true" />}
              aria-label={`Approve request ${r.id}`}
              loading={decide.isPending && decide.variables?.row.key === r.key}
              disabled={r.requestedById === user?.id}
              title={
                r.requestedById === user?.id ? 'You cannot decide your own request' : undefined
              }
              onClick={() => decide.mutate({ row: r, action: 'approve' })}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<X size={14} aria-hidden="true" />}
              aria-label={`Reject request ${r.id}`}
              onClick={() => setRejecting(r)}
            >
              Reject
            </Button>
          </div>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Cancel request ${r.id}`}
            onClick={() => decide.mutate({ row: r, action: 'cancel' })}
          >
            Cancel
          </Button>
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        {approver
          ? 'Requests from staff that remove or damage stock, or move it to another warehouse. Approving applies the change after checking today’s stock.'
          : 'Your recent adjustments and transfers with their status. Pending ones wait for a manager.'}
      </p>
      <DataTable
        caption={approver ? 'Requests waiting for approval' : 'My requests'}
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        isLoading={source.isPending}
        errorMessage={source.errorMessage}
        onRetry={() => void source.refetch()}
        emptyMessage={approver ? 'Nothing waiting for approval.' : 'You have no requests.'}
      />
      <NoteDialog
        open={rejecting !== null}
        title={`Reject request ${rejecting?.id ?? ''}`}
        description={rejecting?.what}
        label="Why is it rejected?"
        confirmLabel="Reject"
        loading={decide.isPending}
        onCancel={() => setRejecting(null)}
        onConfirm={(note) => rejecting && decide.mutate({ row: rejecting, action: 'reject', note })}
      />
    </div>
  )
}
