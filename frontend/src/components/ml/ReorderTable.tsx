import { Link } from 'react-router'

import type { ReorderRecommendation } from '../../types/ml'
import { formatInteger, formatShortDate } from '../../utils/format'
import { DecisionCell } from './DecisionCell'
import { RiskBadge } from './RiskBadge'

/** Products at risk of running out: risk, what to order by when, why, and the decision. */
export function ReorderTable({
  items,
  canDecide,
  busyId,
  onDecide,
}: {
  items: ReorderRecommendation[]
  canDecide: boolean
  busyId?: number | null
  onDecide?: (item: ReorderRecommendation, approve: boolean) => void
}) {
  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">No reorder recommendations.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Reorder recommendations</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th scope="col" className="py-2 pr-3 font-medium">
              Product
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Warehouse
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Stockout risk (14 days)
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Order by
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Quantity
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Why
            </th>
            <th scope="col" className="py-2 font-medium">
              Decision
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                <Link
                  to={`/products/${item.product.id}`}
                  className="font-medium text-blue-700 hover:underline"
                >
                  {item.product.sku}
                </Link>
                <span className="block text-xs text-slate-500">{item.product.name}</span>
              </th>
              <td className="py-2 pr-3">{item.warehouse_code}</td>
              <td className="py-2 pr-3">
                <RiskBadge level={item.priority} probability={item.probability} />
              </td>
              <td className="py-2 pr-3 tabular-nums">{formatShortDate(item.reorder_date)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatInteger(item.quantity)}</td>
              <td className="py-2 pr-3 text-xs text-slate-600">
                {item.reasons.length ? item.reasons.join('; ') : '—'}
              </td>
              <td className="py-2">
                <DecisionCell
                  decision={item}
                  canDecide={canDecide}
                  busy={busyId === item.id}
                  label={`reorder of ${item.product.sku} for ${item.warehouse_code}`}
                  onApprove={() => onDecide?.(item, true)}
                  onReject={() => onDecide?.(item, false)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
