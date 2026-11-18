import { Link } from 'react-router'

import type { DelayRisk } from '../../types/ml'
import { RiskBadge } from './RiskBadge'

/** Shipments on their way by delay risk, with the main reasons. */
export function DelayRiskTable({ items }: { items: DelayRisk[] }) {
  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">No shipments at risk.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Delay risk of shipments on their way</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th scope="col" className="py-2 pr-3 font-medium">
              Order
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Delay risk
            </th>
            <th scope="col" className="py-2 font-medium">
              Why
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => (
            <tr key={item.order_id}>
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                <Link
                  to={`/orders/${item.order_id}`}
                  className="font-medium text-blue-700 hover:underline"
                >
                  {item.order_number}
                </Link>
              </th>
              <td className="py-2 pr-3">
                <RiskBadge level={item.risk_level} probability={item.probability} />
              </td>
              <td className="py-2 text-xs text-slate-600">
                {item.reasons.length ? item.reasons.join('; ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
