import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { listOrders, orderKeys } from '../api/ordersApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { NewOrderDialog } from '../components/orders/NewOrderDialog'
import {
  formatDate,
  isCustomerOnly,
  isOrderManager,
  PRIORITY_TONES,
  STATUS_LABELS,
  STATUS_TONES,
} from '../components/orders/orderFormat'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import { ORDER_STATUSES, type OrderStatus, type OrderSummary } from '../types/orders'
import { formatMoney } from '../utils/format'

const PAGE_SIZE = 25
const URL_DEFAULTS = { q: '', status: '', offset: '0' }

/** Orders: customers see their own, warehouse roles see all. */
export default function OrdersPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const customerOnly = isCustomerOnly(user)
  const canPlace = customerOnly || isOrderManager(user)
  const [creating, setCreating] = useState(false)
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)

  const params = {
    q: filters.q || undefined,
    status: (filters.status || undefined) as OrderStatus | undefined,
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const orders = useApiQuery(orderKeys.list(params), () => listOrders(params), {
    keepPrevious: true,
  })

  const columns: Column<OrderSummary>[] = [
    {
      key: 'number',
      header: 'Order',
      cell: (o) => (
        <div>
          <p className="font-mono text-xs font-medium whitespace-nowrap">{o.order_number}</p>
          <p className="text-xs text-slate-500">{formatDate(o.created_at)}</p>
        </div>
      ),
    },
    ...(customerOnly
      ? []
      : [
          {
            key: 'customer',
            header: 'Customer',
            cell: (o: OrderSummary) => (
              <div>
                <p className="font-medium">{o.customer.name}</p>
                <p className="text-xs text-slate-500">{o.customer.code}</p>
              </div>
            ),
          },
        ]),
    {
      key: 'status',
      header: 'Status',
      cell: (o) => <Badge tone={STATUS_TONES[o.status]}>{STATUS_LABELS[o.status]}</Badge>,
    },
    {
      key: 'priority',
      header: 'Priority',
      cell: (o) =>
        o.priority === 'normal' ? (
          <span className="text-xs text-slate-500">normal</span>
        ) : (
          <Badge tone={PRIORITY_TONES[o.priority]}>{o.priority}</Badge>
        ),
    },
    { key: 'units', header: 'Units', align: 'right', cell: (o) => o.total_quantity },
    { key: 'total', header: 'Total', align: 'right', cell: (o) => formatMoney(o.subtotal) },
    {
      key: 'delivery',
      header: 'Wanted by',
      cell: (o) => <span className="text-xs">{formatDate(o.requested_delivery_date)}</span>,
    },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title={customerOnly ? 'My orders' : 'Orders'}
        description={
          customerOnly
            ? 'Place orders and follow them until they arrive.'
            : 'Every order from creation to delivery.'
        }
        actions={
          canPlace && (
            <Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => setCreating(true)}>
              New order
            </Button>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search orders"
          placeholder={customerOnly ? 'Order number' : 'Order number or customer'}
          value={filters.q}
          onChange={(q) => setFilters({ q })}
        />
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: '', label: 'All statuses' },
            ...ORDER_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] })),
          ]}
        />
      </div>
      <DataTable
        caption="Orders"
        columns={columns}
        rows={orders.data?.items}
        rowKey={(o) => o.id}
        isLoading={orders.isPending}
        isRefreshing={orders.isPlaceholderData}
        errorMessage={orders.errorMessage}
        onRetry={() => void orders.refetch()}
        emptyMessage={
          filters.q || filters.status ? 'No orders match your filters.' : 'No orders yet.'
        }
        onRowClick={(o) => void navigate(`/orders/${o.id}`)}
        pagination={
          orders.data && {
            offset: orders.data.offset,
            limit: orders.data.limit,
            total: orders.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />
      <NewOrderDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
