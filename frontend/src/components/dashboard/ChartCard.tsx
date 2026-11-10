import { BarChart3, Table2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

export interface ChartTable {
  columns: string[]
  rows: (string | number)[][]
}

/**
 * Frame of every chart: title, a short description, and the table view, which shows
 * the same numbers as text (for screen readers, printing and exact values).
 * While new data loads, the previous chart stays visible, dimmed.
 */
export function ChartCard({
  title,
  description,
  table,
  isLoading = false,
  isRefreshing = false,
  errorMessage,
  emptyMessage = 'No data in this period.',
  children,
}: {
  title: string
  description?: string
  table: ChartTable
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
  emptyMessage?: string
  children: ReactNode
}) {
  const [showTable, setShowTable] = useState(false)
  const titleId = useId()
  const empty = table.rows.length === 0

  let body: ReactNode
  if (errorMessage) {
    body = (
      <p role="alert" className="py-10 text-center text-sm text-red-700">
        {errorMessage}
      </p>
    )
  } else if (isLoading) {
    body = <div className="h-64 animate-pulse rounded-lg bg-slate-50" aria-label="Loading chart" />
  } else if (empty) {
    body = <p className="py-10 text-center text-sm text-slate-500">{emptyMessage}</p>
  } else if (showTable) {
    body = (
      <div className="max-h-80 overflow-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              {table.columns.map((column, index) => (
                <th
                  key={column}
                  scope="col"
                  className={`py-2 pr-3 font-medium ${index ? 'text-right' : ''}`}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums">
            {table.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, index) =>
                  index === 0 ? (
                    <th key={index} scope="row" className="py-1.5 pr-3 text-left font-normal">
                      {cell}
                    </th>
                  ) : (
                    <td key={index} className="py-1.5 pr-3 text-right">
                      {cell}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  } else {
    body = (
      <div className={isRefreshing ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
        {children}
      </div>
    )
  }

  return (
    <figure
      aria-labelledby={titleId}
      aria-busy={isLoading || isRefreshing}
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <figcaption>
          <h3 id={titleId} className="font-medium text-slate-900">
            {title}
          </h3>
          {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
        </figcaption>
        {!empty && !isLoading && !errorMessage && (
          <button
            type="button"
            onClick={() => setShowTable((shown) => !shown)}
            aria-pressed={showTable}
            className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            {showTable ? (
              <BarChart3 size={14} aria-hidden="true" />
            ) : (
              <Table2 size={14} aria-hidden="true" />
            )}
            {showTable ? 'Show chart' : 'Show table'}
          </button>
        )}
      </div>
      {body}
    </figure>
  )
}
