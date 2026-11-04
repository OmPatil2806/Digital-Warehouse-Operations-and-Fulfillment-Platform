import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from './Button'

export interface Column<Row> {
  /** Unique column id. */
  key: string
  header: string
  /** Cell content; defaults to row[key]. */
  cell?: (row: Row) => ReactNode
  /** API sort field (e.g. "name"). Makes the header clickable. */
  sortField?: string
  align?: 'left' | 'right'
  className?: string
}

export interface Pagination {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
}

interface DataTableProps<Row> {
  caption: string
  columns: Column<Row>[]
  rows: Row[] | undefined
  rowKey: (row: Row) => string | number
  /** Current sort, e.g. "name" (ascending) or "-name" (descending). */
  sort?: string
  onSortChange?: (sort: string) => void
  pagination?: Pagination
  isLoading?: boolean
  /** True while a new page is loading but the previous rows are still shown. */
  isRefreshing?: boolean
  errorMessage?: string | null
  onRetry?: () => void
  emptyMessage?: ReactNode
  onRowClick?: (row: Row) => void
}

const SKELETON_ROWS = 5

/** Table with sortable headers, pagination and loading / empty / error states. */
export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  pagination,
  isLoading = false,
  isRefreshing = false,
  errorMessage,
  onRetry,
  emptyMessage = 'Nothing found.',
  onRowClick,
}: DataTableProps<Row>) {
  const toggleSort = (field: string) => {
    onSortChange?.(sort === field ? `-${field}` : field)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table
          className={`w-full text-sm ${isRefreshing ? 'opacity-60' : ''}`}
          aria-busy={isLoading || isRefreshing}
        >
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-semibold text-slate-500 uppercase">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={ariaSort(sort, column.sortField)}
                  className={`px-4 py-3 ${column.align === 'right' ? 'text-right' : ''} ${column.className ?? ''}`}
                >
                  {column.sortField && onSortChange ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column.sortField!)}
                      className="inline-flex items-center gap-1 uppercase hover:text-slate-800"
                    >
                      {column.header}
                      <SortIcon sort={sort} field={column.sortField} />
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {errorMessage ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center">
                  <div
                    role="alert"
                    className="inline-flex flex-col items-center gap-3 text-red-700"
                  >
                    <span className="inline-flex items-center gap-2">
                      <AlertCircle size={16} aria-hidden="true" />
                      {errorMessage}
                    </span>
                    {onRetry && (
                      <Button variant="secondary" size="sm" onClick={onRetry}>
                        Try again
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ) : isLoading ? (
              Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <tr key={index} data-testid="skeleton-row">
                  {columns.map((column) => (
                    <td key={column.key} className="px-4 py-3">
                      <div className="h-4 animate-pulse rounded bg-slate-100" />
                    </td>
                  ))}
                </tr>
              ))
            ) : !rows || rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-10 text-center text-slate-500">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={onRowClick ? 'cursor-pointer hover:bg-slate-50' : ''}
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={`px-4 py-3 ${column.align === 'right' ? 'text-right tabular-nums' : ''} ${column.className ?? ''}`}
                    >
                      {column.cell
                        ? column.cell(row)
                        : String((row as Record<string, unknown>)[column.key] ?? '')}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {pagination && !errorMessage && <PaginationBar {...pagination} />}
    </div>
  )
}

function ariaSort(sort: string | undefined, field: string | undefined) {
  if (!field || !sort) return undefined
  if (sort === field) return 'ascending' as const
  if (sort === `-${field}`) return 'descending' as const
  return undefined
}

function SortIcon({ sort, field }: { sort?: string; field: string }) {
  if (sort === field) return <ArrowUp size={12} aria-hidden="true" />
  if (sort === `-${field}`) return <ArrowDown size={12} aria-hidden="true" />
  return <ArrowUpDown size={12} className="opacity-40" aria-hidden="true" />
}

function PaginationBar({ offset, limit, total, onChange }: Pagination) {
  if (total === 0) return null
  const from = offset + 1
  const to = Math.min(offset + limit, total)
  return (
    <nav
      aria-label="Pagination"
      className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm text-slate-600"
    >
      <p>
        Showing <span className="font-medium">{from}</span>–
        <span className="font-medium">{to}</span> of <span className="font-medium">{total}</span>
      </p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<ChevronLeft size={14} aria-hidden="true" />}
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={to >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
          <ChevronRight size={14} aria-hidden="true" />
        </Button>
      </div>
    </nav>
  )
}
