import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'

import type { BinRef, SlottingRecommendation } from '../../types/ml'
import { formatNumber } from '../../utils/format'
import { DecisionCell } from './DecisionCell'
import { formatSecondsPerDay } from './mlFormat'

function BinLabel({ bin }: { bin: BinRef | null }) {
  if (!bin) return <span className="text-slate-500">No pick location yet</span>
  return (
    <span>
      <span className="font-mono text-xs">{bin.location_code}</span>
      <span className="block text-xs text-slate-500">
        {formatNumber(bin.distance_to_packing_m, 'm')} to packing · level {bin.level}
      </span>
    </span>
  )
}

/** Better pick-face bins: from where to where, the picking time saved, and the decision. */
export function SlottingList({
  items,
  canDecide,
  busyId,
  onDecide,
}: {
  items: SlottingRecommendation[]
  canDecide: boolean
  busyId?: number | null
  onDecide?: (item: SlottingRecommendation, approve: boolean) => void
}) {
  if (items.length === 0) {
    return <p className="py-8 text-center text-sm text-slate-500">No slotting recommendations.</p>
  }
  return (
    <ul className="divide-y divide-slate-100" aria-label="Slotting recommendations">
      {items.map((item) => (
        <li key={item.id} className="flex flex-wrap items-start gap-x-6 gap-y-2 py-3">
          <div className="min-w-40">
            <Link
              to={`/products/${item.product.id}`}
              className="font-medium text-blue-700 hover:underline"
            >
              {item.product.sku}
            </Link>
            <span className="block text-xs text-slate-500">
              {item.product.name} · {item.warehouse_code}
            </span>
          </div>
          <div className="flex items-start gap-2 text-sm">
            <BinLabel bin={item.current_bin} />
            <ArrowRight aria-label="moves to" className="mt-0.5 h-4 w-4 text-slate-400" />
            <BinLabel bin={item.recommended_bin} />
          </div>
          <div className="text-sm">
            {item.seconds_saved_per_day !== null ? (
              <>
                <span className="font-semibold tabular-nums">
                  {formatSecondsPerDay(item.seconds_saved_per_day)}
                </span>{' '}
                <span className="text-xs text-slate-500">less picking</span>
              </>
            ) : (
              <span className="text-xs text-slate-500">
                {formatSecondsPerDay(item.recommended_seconds_per_day)} of picking there
              </span>
            )}
          </div>
          <div className="ml-auto">
            <DecisionCell
              decision={item}
              canDecide={canDecide}
              busy={busyId === item.id}
              label={`new bin for ${item.product.sku} in ${item.warehouse_code}`}
              onApprove={() => onDecide?.(item, true)}
              onReject={() => onDecide?.(item, false)}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}
