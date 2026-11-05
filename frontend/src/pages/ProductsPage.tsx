import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { catalogKeys, listCategories, listProducts } from '../api/catalogApi'
import { StatusBadge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { ProductFormDialog } from '../components/products/ProductFormDialog'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { ActiveFilter, Product } from '../types/catalog'
import { formatMoney } from '../utils/format'
import { canEditMasterData } from '../utils/permissions'

const PRODUCTS_PAGE_SIZE = 25

const URL_DEFAULTS = { q: '', category: '', status: 'active', sort: 'sku', offset: '0' }

export default function ProductsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const canEdit = canEditMasterData(user)
  const [creating, setCreating] = useState(false)
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)

  const params = {
    q: filters.q || undefined,
    categoryId: filters.category ? Number(filters.category) : undefined,
    status: filters.status as ActiveFilter,
    sort: filters.sort,
    offset: Number(filters.offset),
    limit: PRODUCTS_PAGE_SIZE,
  }
  const products = useApiQuery(
    [...catalogKeys.products, 'list', params],
    () => listProducts(params),
    {
      keepPrevious: true,
    },
  )
  const categories = useApiQuery(catalogKeys.categories, listCategories)

  const columns: Column<Product>[] = [
    {
      key: 'sku',
      header: 'SKU',
      sortField: 'sku',
      cell: (p) => <span className="font-mono text-xs whitespace-nowrap">{p.sku}</span>,
    },
    {
      key: 'name',
      header: 'Name',
      sortField: 'name',
      cell: (p) => (
        <div>
          <p className="font-medium">{p.name}</p>
          {p.brand && <p className="text-xs text-slate-500">{p.brand}</p>}
        </div>
      ),
    },
    { key: 'category', header: 'Category', cell: (p) => p.category.name },
    {
      key: 'unit_price',
      header: 'Price',
      sortField: 'unit_price',
      align: 'right',
      cell: (p) => formatMoney(p.unit_price),
    },
    {
      key: 'margin',
      header: 'Margin',
      align: 'right',
      cell: (p) => (
        <span className={Number(p.margin) < 0 ? 'text-red-600' : ''}>{formatMoney(p.margin)}</span>
      ),
    },
    { key: 'status', header: 'Status', cell: (p) => <StatusBadge active={p.is_active} /> },
  ]

  const categoryOptions = [
    { value: '', label: 'All categories' },
    ...(categories.data?.items ?? []).map((c) => ({ value: String(c.id), label: c.name })),
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Products"
        description="Every stock-keeping unit the warehouse can store and ship."
        actions={
          canEdit && (
            <Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => setCreating(true)}>
              New product
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search products"
          placeholder="SKU, name, brand or barcode"
          value={filters.q}
          onChange={(q) => setFilters({ q })}
        />
        <FilterSelect
          label="Category"
          value={filters.category}
          onChange={(category) => setFilters({ category })}
          options={categoryOptions}
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
        caption="Products"
        columns={columns}
        rows={products.data?.items}
        rowKey={(p) => p.id}
        sort={filters.sort}
        onSortChange={(sort) => setFilters({ sort })}
        isLoading={products.isPending}
        isRefreshing={products.isPlaceholderData}
        errorMessage={products.errorMessage}
        onRetry={() => void products.refetch()}
        emptyMessage={
          filters.q || filters.category ? 'No products match your filters.' : 'No products yet.'
        }
        onRowClick={(p) => void navigate(`/products/${p.id}`)}
        pagination={
          products.data && {
            offset: products.data.offset,
            limit: products.data.limit,
            total: products.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />

      <ProductFormDialog
        open={creating}
        onClose={() => setCreating(false)}
        onSaved={(product) => void navigate(`/products/${product.id}`)}
      />
    </div>
  )
}
