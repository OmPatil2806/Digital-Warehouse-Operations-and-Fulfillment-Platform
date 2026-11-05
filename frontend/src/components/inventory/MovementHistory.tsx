import { listMovements, inventoryKeys } from '../../api/inventoryApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { Movement, MovementType } from '../../types/inventory'
import { Badge } from '../common/Badge'
import { DataTable, type Column } from '../common/DataTable'
import {
  describeBalance,
  describeChange,
  describeReference,
  formatDateTime,
  MOVEMENT_LABELS,
  MOVEMENT_TONES,
} from './movementFormat'

const PAGE_SIZE = 25

const COLUMNS: Column<Movement>[] = [
  {
    key: 'when',
    header: 'When',
    cell: (m) => <span className="whitespace-nowrap">{formatDateTime(m.created_at)}</span>,
  },
  {
    key: 'type',
    header: 'Type',
    cell: (m) => (
      <Badge tone={MOVEMENT_TONES[m.movement_type]}>{MOVEMENT_LABELS[m.movement_type]}</Badge>
    ),
  },
  {
    key: 'product',
    header: 'Product',
    cell: (m) => (
      <div>
        <p className="font-mono text-xs">{m.product.sku}</p>
        <p className="text-xs text-slate-500">{m.product.name}</p>
      </div>
    ),
  },
  {
    key: 'bin',
    header: 'Bin',
    cell: (m) => <span className="font-mono text-xs whitespace-nowrap">{m.bin.location_code}</span>,
  },
  {
    key: 'change',
    header: 'Change',
    cell: (m) => <span className="font-medium whitespace-nowrap">{describeChange(m)}</span>,
  },
  {
    key: 'after',
    header: 'After',
    cell: (m) => (
      <span className="text-xs whitespace-nowrap text-slate-600">{describeBalance(m)}</span>
    ),
  },
  {
    key: 'why',
    header: 'Reference / reason',
    cell: (m) => (
      <div className="text-xs">
        {describeReference(m) && <p className="font-medium">{describeReference(m)}</p>}
        {m.reason && <p className="text-slate-500">{m.reason}</p>}
      </div>
    ),
  },
  {
    key: 'by',
    header: 'By',
    cell: (m) => <span className="text-xs">{m.created_by?.full_name ?? 'System'}</span>,
  },
]

interface MovementHistoryProps {
  productId?: number
  binId?: number
  movementType?: MovementType
  offset: number
  onOffsetChange: (offset: number) => void
}

/** Immutable movement history (newest first) with the change and balance of each entry. */
export function MovementHistory({
  productId,
  binId,
  movementType,
  offset,
  onOffsetChange,
}: MovementHistoryProps) {
  const params = { productId, binId, movementType, offset, limit: PAGE_SIZE }
  const movements = useApiQuery(inventoryKeys.movements(params), () => listMovements(params), {
    keepPrevious: true,
  })

  return (
    <DataTable
      caption="Movement history"
      columns={COLUMNS}
      rows={movements.data?.items}
      rowKey={(m) => m.id}
      isLoading={movements.isPending}
      isRefreshing={movements.isPlaceholderData}
      errorMessage={movements.errorMessage}
      onRetry={() => void movements.refetch()}
      emptyMessage="No movements match your filters."
      pagination={
        movements.data && {
          offset: movements.data.offset,
          limit: movements.data.limit,
          total: movements.data.total,
          onChange: onOffsetChange,
        }
      }
    />
  )
}
