import { ClipboardCheck } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { inventoryKeys, listCycleCounts, startCycleCount } from '../../api/inventoryApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { CycleCountSummary } from '../../types/inventory'
import type { BinDetail } from '../../types/warehouse'
import { Badge } from '../common/Badge'
import { Button } from '../common/Button'
import { DataTable, type Column } from '../common/DataTable'
import { Modal } from '../common/Modal'
import { TextField } from '../form/fields'
import { COUNT_STATUS_TONES, formatDateTime } from './movementFormat'
import { BinCodeField } from './Pickers'

const COLUMNS: Column<CycleCountSummary>[] = [
  { key: 'id', header: 'Count', cell: (c) => <span className="font-medium">#{c.id}</span> },
  {
    key: 'bin',
    header: 'Bin',
    cell: (c) => <span className="font-mono text-xs">{c.bin.location_code}</span>,
  },
  {
    key: 'started',
    header: 'Started',
    cell: (c) => (
      <div>
        <p className="whitespace-nowrap">{formatDateTime(c.created_at)}</p>
        <p className="text-xs text-slate-500">by {c.requested_by?.full_name ?? 'System'}</p>
      </div>
    ),
  },
  {
    key: 'status',
    header: 'Status',
    cell: (c) => <Badge tone={COUNT_STATUS_TONES[c.status]}>{c.status}</Badge>,
  },
]

/** List of cycle counts and a button to start counting a bin. */
export function CycleCountsPanel({
  offset,
  onOffsetChange,
}: {
  offset: number
  onOffsetChange: (offset: number) => void
}) {
  const navigate = useNavigate()
  const [starting, setStarting] = useState(false)
  const params = { offset, limit: 25 }
  const counts = useApiQuery(
    [...inventoryKeys.cycleCounts, params],
    () => listCycleCounts(params),
    {
      keepPrevious: true,
    },
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-500">
          Count a bin, enter what you find, and a manager approves the differences.
        </p>
        <Button
          icon={<ClipboardCheck size={16} aria-hidden="true" />}
          onClick={() => setStarting(true)}
        >
          Start count
        </Button>
      </div>
      <DataTable
        caption="Cycle counts"
        columns={COLUMNS}
        rows={counts.data?.items}
        rowKey={(c) => c.id}
        isLoading={counts.isPending}
        isRefreshing={counts.isPlaceholderData}
        errorMessage={counts.errorMessage}
        onRetry={() => void counts.refetch()}
        emptyMessage="No cycle counts yet."
        onRowClick={(c) => void navigate(`/inventory/cycle-counts/${c.id}`)}
        pagination={
          counts.data && {
            offset: counts.data.offset,
            limit: counts.data.limit,
            total: counts.data.total,
            onChange: onOffsetChange,
          }
        }
      />
      {starting && <StartCountDialog onClose={() => setStarting(false)} />}
    </div>
  )
}

function StartCountDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [bin, setBin] = useState<BinDetail | null>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState<string>()
  const start = useApiMutation(startCycleCount, {
    invalidates: [inventoryKeys.cycleCounts],
    toastOnError: false,
    onSuccess: (count) => void navigate(`/inventory/cycle-counts/${count.id}`),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="Start a cycle count"
      description="The system records what it expects in the bin; then you count."
      dismissible={!start.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={start.isPending}>
            Cancel
          </Button>
          <Button
            loading={start.isPending}
            onClick={() => {
              if (!bin) return setError('Enter a bin code')
              start.mutate({ bin_id: bin.id, note: note.trim() || undefined })
            }}
          >
            Start counting
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <BinCodeField label="Bin to count" value={bin} onChange={setBin} error={error} />
        <TextField
          label="Note"
          value={note}
          maxLength={255}
          onChange={(event) => setNote(event.target.value)}
          hint="Optional, e.g. Weekly count zone A"
        />
        {start.errorMessage && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {start.errorMessage}
          </p>
        )}
      </div>
    </Modal>
  )
}
