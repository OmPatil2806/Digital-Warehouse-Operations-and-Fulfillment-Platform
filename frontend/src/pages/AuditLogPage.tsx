import { auditKeys, listAuditLogs } from '../api/alertsApi'
import { Badge, type BadgeTone } from '../components/common/Badge'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { formatDateTime } from '../components/inventory/movementFormat'
import { useApiQuery } from '../hooks/useApiQuery'
import { useUrlState } from '../hooks/useUrlState'
import type { AuditChanges, AuditLogEntry } from '../types/alerts'

const PAGE_SIZE = 50
const URL_DEFAULTS = { entity: '', action: '', offset: '0' }

const ENTITY_TYPES = [
  ['user', 'Users'],
  ['product', 'Products'],
  ['category', 'Categories'],
  ['supplier', 'Suppliers'],
  ['supplier_product', 'Supplier offers'],
  ['warehouse', 'Warehouses'],
  ['zone', 'Zones'],
  ['rack', 'Racks'],
  ['shelf', 'Shelves'],
  ['bin', 'Bins'],
  ['inventory', 'Stock'],
  ['stock_adjustment', 'Adjustment requests'],
  ['stock_transfer', 'Transfers'],
  ['cycle_count', 'Cycle counts'],
] as const

const ACTIONS = [
  'create',
  'update',
  'delete',
  'inventory.receive',
  'inventory.adjust',
  'inventory.transfer',
  'inventory.reserve',
  'inventory.release',
  'stock_adjustment.request',
  'stock_adjustment.approve',
  'stock_adjustment.reject',
  'stock_transfer.request',
  'stock_transfer.approve',
  'stock_transfer.reject',
  'cycle_count.start',
  'cycle_count.approve',
]

function actionTone(action: string): BadgeTone {
  if (action === 'delete' || action.endsWith('.reject')) return 'danger'
  if (action === 'create' || action.endsWith('.approve')) return 'success'
  if (action.startsWith('inventory.')) return 'info'
  return 'neutral'
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '∅'
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

/** "price: 100.00 → 129.90" lines for each changed field. */
function changeLines(changes: AuditChanges | null): string[] {
  if (!changes) return []
  return Object.entries(changes).map(([field, change]) => {
    if (change && typeof change === 'object' && ('old' in change || 'new' in change)) {
      const c = change as { old?: unknown; new?: unknown }
      if (!('old' in c)) return `${field}: ${show(c.new)}`
      if (!('new' in c)) return `${field}: ${show(c.old)} (removed)`
      return `${field}: ${show(c.old)} → ${show(c.new)}`
    }
    return `${field}: ${show(change)}`
  })
}

const COLUMNS: Column<AuditLogEntry>[] = [
  {
    key: 'when',
    header: 'When',
    cell: (e) => <span className="text-xs whitespace-nowrap">{formatDateTime(e.created_at)}</span>,
  },
  {
    key: 'who',
    header: 'Who',
    cell: (e) => <span className="text-xs">{e.actor_email ?? 'System'}</span>,
  },
  {
    key: 'action',
    header: 'Action',
    cell: (e) => <Badge tone={actionTone(e.action)}>{e.action}</Badge>,
  },
  {
    key: 'record',
    header: 'Record',
    cell: (e) => (
      <span className="font-mono text-xs whitespace-nowrap">
        {e.entity_type}
        {e.entity_id != null && ` #${e.entity_id}`}
      </span>
    ),
  },
  {
    key: 'details',
    header: 'Details',
    cell: (e) => {
      const lines = changeLines(e.changes)
      return (
        <div className="text-xs">
          {e.summary && <p className="font-medium">{e.summary}</p>}
          {lines.length > 0 && (
            <details className="mt-1 text-slate-600">
              <summary className="cursor-pointer text-blue-700">
                {lines.length} field{lines.length === 1 ? '' : 's'}
              </summary>
              <ul className="mt-1 space-y-0.5 font-mono break-all">
                {lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )
    },
  },
]

/** Admin-only, read-only view of the audit log (who changed what, when; old and new values). */
export default function AuditLogPage() {
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const params = {
    entityType: filters.entity || undefined,
    action: filters.action || undefined,
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const entries = useApiQuery(auditKeys.list(params), () => listAuditLogs(params), {
    keepPrevious: true,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Audit log"
        description="Every change to users, master data and stock, newest first. Entries can never be edited or deleted."
      />
      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect
          label="Record type"
          value={filters.entity}
          onChange={(entity) => setFilters({ entity })}
          options={[
            { value: '', label: 'All records' },
            ...ENTITY_TYPES.map(([value, label]) => ({ value, label })),
          ]}
        />
        <FilterSelect
          label="Action"
          value={filters.action}
          onChange={(action) => setFilters({ action })}
          options={[
            { value: '', label: 'All actions' },
            ...ACTIONS.map((a) => ({ value: a, label: a })),
          ]}
        />
      </div>
      <DataTable
        caption="Audit log"
        columns={COLUMNS}
        rows={entries.data?.items}
        rowKey={(e) => e.id}
        isLoading={entries.isPending}
        isRefreshing={entries.isPlaceholderData}
        errorMessage={entries.errorMessage}
        onRetry={() => void entries.refetch()}
        emptyMessage="No entries match your filters."
        pagination={
          entries.data && {
            offset: entries.data.offset,
            limit: entries.data.limit,
            total: entries.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />
    </div>
  )
}
