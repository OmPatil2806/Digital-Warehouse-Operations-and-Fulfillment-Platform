import { AlarmClock, Plus } from 'lucide-react'
import { useState } from 'react'

import { alertKeys } from '../api/alertsApi'
import {
  checkOverduePurchaseOrders,
  listPurchaseOrders,
  purchaseOrderKeys,
} from '../api/purchasingApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { CheckboxField } from '../components/form/fields'
import { formatDate, isOrderManager } from '../components/orders/orderFormat'
import {
  NewPurchaseOrderDialog,
  PurchaseOrderDialog,
} from '../components/purchasing/PurchaseOrderDialogs'
import { PO_STATUS_LABELS, PO_TONES } from '../components/purchasing/purchasingFormat'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { PurchaseOrder, PurchaseOrderStatus } from '../types/purchasing'
import { formatMoney } from '../utils/format'

const PAGE_SIZE = 25
const URL_DEFAULTS = { q: '', status: '', overdue: '', offset: '0' }

/** Supplier purchase orders: managers order, the warehouse receives the goods. */
export default function PurchaseOrdersPage() {
  const { user } = useAuth()
  const manager = isOrderManager(user)
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<PurchaseOrder | null>(null)

  const params = {
    q: filters.q,
    status: filters.status,
    overdue: filters.overdue === '1',
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const orders = useApiQuery(purchaseOrderKeys.list(params), () => listPurchaseOrders(params), {
    keepPrevious: true,
  })
  const overdue = useApiMutation(checkOverduePurchaseOrders, {
    invalidates: [purchaseOrderKeys.all, alertKeys.all],
    successMessage: (late) =>
      late.length
        ? `${late.length} purchase order(s) overdue — see Alerts`
        : 'No purchase order is overdue',
  })

  const columns: Column<PurchaseOrder>[] = [
    {
      key: 'number',
      header: 'PO',
      cell: (po) => (
        <div>
          <p className="font-mono text-xs font-medium">{po.po_number}</p>
          <p className="text-xs text-slate-500">{formatDate(po.created_at)}</p>
        </div>
      ),
    },
    {
      key: 'supplier',
      header: 'Supplier',
      cell: (po) => (
        <div>
          <p className="text-sm">{po.supplier.name}</p>
          <p className="font-mono text-xs text-slate-500">{po.supplier.code}</p>
        </div>
      ),
    },
    {
      key: 'items',
      header: 'Items',
      cell: (po) => (
        <span className="text-xs">
          {po.items
            .map((i) => `${i.quantity_received}/${i.quantity} × ${i.product.sku}`)
            .join(', ')}
        </span>
      ),
    },
    { key: 'total', header: 'Total', align: 'right', cell: (po) => formatMoney(po.total_cost) },
    {
      key: 'expected',
      header: 'Expected',
      cell: (po) => (
        <span
          className={`text-xs whitespace-nowrap ${po.is_overdue ? 'font-medium text-red-700' : ''}`}
        >
          {formatDate(po.expected_date)}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (po) => (
        <span className="flex flex-wrap gap-1">
          <Badge tone={PO_TONES[po.status]}>{PO_STATUS_LABELS[po.status]}</Badge>
          {po.is_overdue && <Badge tone="danger">overdue</Badge>}
        </span>
      ),
    },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Purchase orders"
        description="Stock ordered from suppliers, and what has arrived so far."
        actions={
          manager && (
            <div className="flex gap-2">
              <Button
                variant="secondary"
                icon={<AlarmClock size={16} aria-hidden="true" />}
                loading={overdue.isPending}
                onClick={() => overdue.mutate(undefined)}
              >
                Check overdue
              </Button>
              <Button
                icon={<Plus size={16} aria-hidden="true" />}
                onClick={() => setCreating(true)}
              >
                New purchase order
              </Button>
            </div>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search purchase orders"
          placeholder="PO number or supplier"
          value={filters.q}
          onChange={(q) => setFilters({ q })}
        />
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: '', label: 'All statuses' },
            ...(Object.keys(PO_STATUS_LABELS) as PurchaseOrderStatus[]).map((s) => ({
              value: s,
              label: PO_STATUS_LABELS[s],
            })),
          ]}
        />
        <CheckboxField
          label="Only overdue"
          checked={filters.overdue === '1'}
          onChange={(event) => setFilters({ overdue: event.target.checked ? '1' : '' })}
        />
      </div>
      <DataTable
        caption="Purchase orders"
        columns={columns}
        rows={orders.data?.items}
        rowKey={(po) => po.id}
        isLoading={orders.isPending}
        isRefreshing={orders.isPlaceholderData}
        errorMessage={orders.errorMessage}
        onRetry={() => void orders.refetch()}
        emptyMessage="No purchase orders match."
        onRowClick={setOpen}
        pagination={
          orders.data && {
            offset: orders.data.offset,
            limit: orders.data.limit,
            total: orders.data.total,
            onChange: (next) => setFilters({ offset: String(next) }),
          }
        }
      />
      <NewPurchaseOrderDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(po) => {
          setCreating(false)
          setOpen(po)
        }}
      />
      <PurchaseOrderDialog po={open} canManage={manager} onClose={() => setOpen(null)} />
    </div>
  )
}
