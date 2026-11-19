import { BrainCircuit } from 'lucide-react'
import { Link } from 'react-router'

import { getMlSummary, mlKeys } from '../../api/mlApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import { formatInteger, formatShortDate } from '../../utils/format'
import { KpiCard } from '../dashboard/KpiCard'
import { formatProbability, formatSecondsPerDay, formatUnits } from './mlFormat'

/** The dashboard's ML box: predicted stockouts, risky deliveries, coming demand, slotting. */
export function MLSummaryCards() {
  const query = useApiQuery(mlKeys.summary, getMlSummary)
  const s = query.data
  const loading = query.isPending

  if (query.errorMessage) {
    return (
      <p role="alert" className="text-sm text-red-700">
        ML insights could not be loaded: {query.errorMessage}
      </p>
    )
  }
  if (!loading && !s?.as_of) {
    return (
      <section
        aria-labelledby="ml-heading"
        className="flex items-start gap-3 rounded-xl border border-dashed border-slate-300 p-4"
      >
        <BrainCircuit size={20} className="mt-0.5 text-slate-400" aria-hidden="true" />
        <div>
          <h3 id="ml-heading" className="font-medium text-slate-700">
            ML insights
          </h3>
          <p className="text-sm text-slate-500">
            No predictions yet: train and score the models (scripts/train_models.py, then
            scripts/score_models.py).
          </p>
        </div>
      </section>
    )
  }
  return (
    <section aria-labelledby="ml-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="ml-heading" className="flex items-center gap-2 font-medium text-slate-800">
          <BrainCircuit size={18} aria-hidden="true" /> ML insights
        </h3>
        <p className="text-xs text-slate-500">
          {s?.as_of ? `As of ${formatShortDate(s.as_of)} · ` : ''}
          <Link to="/ml-insights" className="text-blue-700 hover:underline">
            Open ML insights
          </Link>
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Predicted stockouts"
          isLoading={loading}
          value={formatInteger(s?.stockouts_pending)}
          status={
            s?.stockouts_high
              ? { tone: 'critical', label: `${s.stockouts_high} high risk` }
              : undefined
          }
          detail="Within 14 days, waiting for a decision"
        />
        <KpiCard
          label="High-risk deliveries"
          isLoading={loading}
          value={formatInteger(s?.orders_high_risk)}
          status={s?.orders_high_risk ? { tone: 'warning', label: 'May arrive late' } : undefined}
          detail={`Of ${formatInteger(s?.orders_on_the_way)} shipments on their way (${formatInteger(s?.orders_at_risk)} medium or high)`}
        />
        <KpiCard
          label="Demand next 7 days"
          isLoading={loading}
          value={`${formatUnits(s?.forecast_units_7_days ?? 0)} units`}
          detail={
            <>
              {formatUnits(s?.forecast_units_30_days ?? 0)} units in the next 30 days
              {s?.forecast_error != null && (
                <>
                  <br />
                  Forecast error {formatProbability(s.forecast_error)} on the last{' '}
                  {s.forecast_error_days} days
                </>
              )}
            </>
          }
        />
        <KpiCard
          label="Slotting moves"
          isLoading={loading}
          value={formatInteger(s?.slotting_pending)}
          detail={`Would save ${formatSecondsPerDay(s?.slotting_seconds_saved_per_day ?? 0)} of picking`}
        />
      </div>
    </section>
  )
}
