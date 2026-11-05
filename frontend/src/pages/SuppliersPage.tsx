import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { catalogKeys, listSuppliers } from '../api/catalogApi'
import { StatusBadge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { SupplierFormDialog } from '../components/suppliers/SupplierFormDialog'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { ActiveFilter, Supplier } from '../types/catalog'
import { formatPercent } from '../utils/format'
import { canEditMasterData } from '../utils/permissions'

const PAGE_SIZE = 25
const URL_DEFAULTS = { q: '', status: 'active', sort: 'code', offset: '0' }

export default function SuppliersPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canEdit = canEditMasterData(user)
  const [creating, setCreating] = useState(false)
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)

  const params = {
    q: filters.q || undefined,
    status: filters.status as ActiveFilter,
    sort: filters.sort,
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const suppliers = useApiQuery(
    [...catalogKeys.suppliers, 'list', params],
    () => listSuppliers(params),
    {
      keepPrevious: true,
    },
  )

  const columns: Column<Supplier>[] = [
    {
      key: 'code',
      header: 'Code',
      sortField: 'code',
      cell: (s) => <span className="font-mono text-xs whitespace-nowrap">{s.code}</span>,
    },
    {
      key: 'name',
      header: 'Name',
      sortField: 'name',
      cell: (s) => <span className="font-medium">{s.name}</span>,
    },
    { key: 'country', header: 'Country', cell: (s) => s.country ?? '—' },
    {
      key: 'lead_time_days',
      header: 'Lead time',
      sortField: 'lead_time_days',
      align: 'right',
      cell: (s) => `${s.lead_time_days} days`,
    },
    {
      key: 'reliability_score',
      header: 'Reliability',
      sortField: 'reliability_score',
      align: 'right',
      cell: (s) => (
        <span className={Number(s.reliability_score) < 0.9 ? 'text-amber-700' : ''}>
          {formatPercent(s.reliability_score)}
        </span>
      ),
    },
    { key: 'status', header: 'Status', cell: (s) => <StatusBadge active={s.is_active} /> },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Suppliers"
        description="Companies the warehouse buys products from."
        actions={
          canEdit && (
            <Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => setCreating(true)}>
              New supplier
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search suppliers"
          placeholder="Code, name, email or country"
          value={filters.q}
          onChange={(q) => setFilters({ q })}
        />
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: 'active', label: 'Active' },
            { value: 'archived', label: 'Archived' },
            { value: 'all', label: 'All' },
          ]}
        />
      </div>

      <DataTable
        caption="Suppliers"
        columns={columns}
        rows={suppliers.data?.items}
        rowKey={(s) => s.id}
        sort={filters.sort}
        onSortChange={(sort) => setFilters({ sort })}
        isLoading={suppliers.isPending}
        isRefreshing={suppliers.isPlaceholderData}
        errorMessage={suppliers.errorMessage}
        onRetry={() => void suppliers.refetch()}
        emptyMessage={filters.q ? 'No suppliers match your search.' : 'No suppliers yet.'}
        onRowClick={(s) => void navigate(`/suppliers/${s.id}`)}
        pagination={
          suppliers.data && {
            offset: suppliers.data.offset,
            limit: suppliers.data.limit,
            total: suppliers.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />

      <SupplierFormDialog
        open={creating}
        onClose={() => setCreating(false)}
        onSaved={(supplier) => void navigate(`/suppliers/${supplier.id}`)}
      />
    </div>
  )
}
