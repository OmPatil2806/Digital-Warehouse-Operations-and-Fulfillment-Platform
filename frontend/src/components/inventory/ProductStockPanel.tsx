import { History } from 'lucide-react'
import { Link } from 'react-router'

import { getProductStock, inventoryKeys } from '../../api/inventoryApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { InventoryRow } from '../../types/inventory'
import { formatInteger } from '../../utils/format'
import { Badge } from '../common/Badge'
import { DataTable, type Column } from '../common/DataTable'

const BIN_COLUMNS: Column<InventoryRow>[] = [
  {
    key: 'bin',
    header: 'Bin',
    cell: (r) => <span className="font-mono text-xs">{r.bin.location_code}</span>,
  },
  { key: 'on_hand', header: 'On hand', align: 'right', cell: (r) => r.quantity_on_hand },
  { key: 'reserved', header: 'Reserved', align: 'right', cell: (r) => r.quantity_reserved },
  { key: 'damaged', header: 'Damaged', align: 'right', cell: (r) => r.quantity_damaged },
  {
    key: 'available',
    header: 'Available',
    align: 'right',
    cell: (r) => <span className="font-semibold">{r.quantity_available}</span>,
  },
]

function Total({
  label,
  value,
  strong = false,
}: {
  label: string
  value: number
  strong?: boolean
}) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className={`mt-1 text-xl ${strong ? 'font-semibold text-slate-900' : 'text-slate-700'}`}>
        {formatInteger(value)}
      </dd>
    </div>
  )
}

/** "Where is this product?": totals over all bins and the bins that hold it. */
export function ProductStockPanel({ productId }: { productId: number }) {
  const stock = useApiQuery(inventoryKeys.product(productId), () => getProductStock(productId))
  const s = stock.data

  return (
    <div className="space-y-4">
      {stock.errorMessage && (
        <p role="alert" className="text-sm text-red-700">
          {stock.errorMessage}
        </p>
      )}
      {s && (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <dl className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Total label="Available" value={s.quantity_available} strong />
            <Total label="On hand" value={s.quantity_on_hand} />
            <Total label="Reserved" value={s.quantity_reserved} />
            <Total label="Damaged" value={s.quantity_damaged} />
          </dl>
          <div className="flex flex-col items-end gap-2">
            {s.is_low_stock && (
              <Badge tone={s.quantity_available === 0 ? 'danger' : 'warning'}>
                {s.quantity_available === 0 ? 'Out of stock' : 'Low stock'} · minimum{' '}
                {formatInteger(s.min_stock)}
              </Badge>
            )}
            <Link
              to={`/inventory?view=movements&product=${productId}`}
              className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline"
            >
              <History size={14} aria-hidden="true" /> Movement history
            </Link>
          </div>
        </div>
      )}
      <DataTable
        caption="Bins holding this product"
        columns={BIN_COLUMNS}
        rows={s?.bins}
        rowKey={(r) => r.id}
        isLoading={stock.isPending}
        emptyMessage="Not in stock in any bin."
      />
    </div>
  )
}
