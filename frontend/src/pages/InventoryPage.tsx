import { X } from 'lucide-react'
import { useId } from 'react'

import { getProductStock, inventoryKeys, listInventory } from '../api/inventoryApi'
import { listWarehouses, warehouseKeys } from '../api/warehouseApi'
import { DataTable, type Column } from '../components/common/DataTable'
import { Modal } from '../components/common/Modal'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { MovementHistory } from '../components/inventory/MovementHistory'
import { MOVEMENT_LABELS } from '../components/inventory/movementFormat'
import { ProductStockPanel } from '../components/inventory/ProductStockPanel'
import { useApiQuery } from '../hooks/useApiQuery'
import { useUrlState } from '../hooks/useUrlState'
import { MOVEMENT_TYPES, type InventoryRow, type MovementType } from '../types/inventory'

const PAGE_SIZE = 25
// view: "stock" (per product and bin) or "movements" (history).
// product: in the stock view opens "where is this product?"; in the history it filters.
const URL_DEFAULTS = { view: 'stock', q: '', warehouse: '', product: '', type: '', offset: '0' }

const STOCK_COLUMNS: Column<InventoryRow>[] = [
  {
    key: 'bin',
    header: 'Bin',
    cell: (r) => <span className="font-mono text-xs whitespace-nowrap">{r.bin.location_code}</span>,
  },
  {
    key: 'product',
    header: 'Product',
    cell: (r) => (
      <div>
        <p className="font-mono text-xs">{r.product.sku}</p>
        <p className="font-medium">{r.product.name}</p>
      </div>
    ),
  },
  { key: 'on_hand', header: 'On hand', align: 'right', cell: (r) => r.quantity_on_hand },
  { key: 'reserved', header: 'Reserved', align: 'right', cell: (r) => r.quantity_reserved || '—' },
  {
    key: 'damaged',
    header: 'Damaged',
    align: 'right',
    cell: (r) =>
      r.quantity_damaged ? <span className="text-red-700">{r.quantity_damaged}</span> : '—',
  },
  {
    key: 'available',
    header: 'Available',
    align: 'right',
    cell: (r) => (
      <span className={`font-semibold ${r.quantity_available === 0 ? 'text-red-700' : ''}`}>
        {r.quantity_available}
      </span>
    ),
  },
]

/** Stock at bin level (on hand, reserved, damaged, available) and its movement history. */
export default function InventoryPage() {
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const tabsId = useId()
  const productId = filters.product ? Number(filters.product) : undefined
  const offset = Number(filters.offset)

  const warehouses = useApiQuery(warehouseKeys.all, listWarehouses)
  const params = {
    q: filters.q || undefined,
    warehouseId: filters.warehouse ? Number(filters.warehouse) : undefined,
    offset,
    limit: PAGE_SIZE,
  }
  const stock = useApiQuery(inventoryKeys.stock(params), () => listInventory(params), {
    keepPrevious: true,
    enabled: filters.view === 'stock',
  })
  // Only for the product's name in the dialog title / filter chip (shared, cached query).
  const product = useApiQuery(
    inventoryKeys.product(productId ?? 0),
    () => getProductStock(productId ?? 0),
    { enabled: productId !== undefined },
  )
  const productLabel = product.data
    ? `${product.data.product.sku} · ${product.data.product.name}`
    : `Product #${productId}`

  const tabs = [
    { view: 'stock', label: 'Stock' },
    { view: 'movements', label: 'Movement history' },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Inventory"
        description="Stock per product and bin. Available = on hand − reserved − damaged."
      />

      <div
        role="tablist"
        aria-label="Inventory views"
        className="flex gap-1 border-b border-slate-200"
      >
        {tabs.map((tab) => {
          const selected = filters.view === tab.view
          return (
            <button
              key={tab.view}
              type="button"
              role="tab"
              id={`${tabsId}-${tab.view}`}
              aria-selected={selected}
              aria-controls={`${tabsId}-panel`}
              onClick={() => setFilters({ view: tab.view, product: '', type: '' })}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
                selected
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              {tab.label}
            </button>
          )
        })}
      </div>

      <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${filters.view}`}>
        {filters.view === 'movements' ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <FilterSelect
                label="Movement type"
                value={filters.type}
                onChange={(type) => setFilters({ type })}
                options={[
                  { value: '', label: 'All types' },
                  ...MOVEMENT_TYPES.map((t) => ({ value: t, label: MOVEMENT_LABELS[t] })),
                ]}
              />
              {productId !== undefined && (
                <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 py-1 pr-1 pl-3 text-sm text-blue-800">
                  {productLabel}
                  <button
                    type="button"
                    aria-label="Show all products"
                    onClick={() => setFilters({ product: '' })}
                    className="rounded-full p-1 hover:bg-blue-100"
                  >
                    <X size={12} aria-hidden="true" />
                  </button>
                </span>
              )}
            </div>
            <MovementHistory
              productId={productId}
              movementType={(filters.type || undefined) as MovementType | undefined}
              offset={offset}
              onOffsetChange={(next) => setFilters({ offset: String(next) })}
            />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <SearchInput
                label="Search stock"
                placeholder="SKU, product name or bin code"
                value={filters.q}
                onChange={(q) => setFilters({ q })}
              />
              <FilterSelect
                label="Warehouse"
                value={filters.warehouse}
                onChange={(warehouse) => setFilters({ warehouse })}
                options={[
                  { value: '', label: 'All warehouses' },
                  ...(warehouses.data ?? []).map((w) => ({
                    value: String(w.id),
                    label: `${w.code} · ${w.name}`,
                  })),
                ]}
              />
            </div>
            <DataTable
              caption="Stock per bin"
              columns={STOCK_COLUMNS}
              rows={stock.data?.items}
              rowKey={(r) => r.id}
              isLoading={stock.isPending}
              isRefreshing={stock.isPlaceholderData}
              errorMessage={stock.errorMessage}
              onRetry={() => void stock.refetch()}
              emptyMessage={
                filters.q || filters.warehouse ? 'No stock matches your filters.' : 'No stock yet.'
              }
              onRowClick={(r) =>
                setFilters({ product: String(r.product.id), offset: filters.offset })
              }
              pagination={
                stock.data && {
                  offset: stock.data.offset,
                  limit: stock.data.limit,
                  total: stock.data.total,
                  onChange: (next) => setFilters({ offset: String(next) }),
                }
              }
            />
          </div>
        )}
      </div>

      <Modal
        open={filters.view === 'stock' && productId !== undefined}
        onClose={() => setFilters({ product: '', offset: filters.offset })}
        title={productLabel}
        description="Where this product is stored"
        size="lg"
      >
        {productId !== undefined && <ProductStockPanel productId={productId} />}
      </Modal>
    </div>
  )
}
