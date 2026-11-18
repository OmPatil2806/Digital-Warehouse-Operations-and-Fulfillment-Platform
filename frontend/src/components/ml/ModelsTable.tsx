import type { ModelSummary } from '../../types/ml'
import { formatInteger, formatShortDate } from '../../utils/format'
import { Badge } from '../common/Badge'
import { formatProbability } from './mlFormat'

/** Per use case: its title and the test metric that chose the model, in words. */
const USE_CASES: Record<string, { title: string; metric: string; label: string }> = {
  demand_forecasting: {
    title: 'Demand forecasting',
    metric: 'wape_totals',
    label: 'error of 7/14/30-day totals',
  },
  reorder: {
    title: 'Reorder recommendation',
    metric: 'pr_auc',
    label: 'stockout warnings (PR-AUC)',
  },
  movement_classification: {
    title: 'Movement classification',
    metric: 'fast_pick_share',
    label: 'next picks from fast movers',
  },
  slotting: { title: 'Slotting', metric: 'pick_time_reduction', label: 'picking time saved' },
  delay_prediction: {
    title: 'Order-delay prediction',
    metric: 'pr_auc',
    label: 'late-delivery warnings (PR-AUC)',
  },
  recommendation: {
    title: 'Product recommendation',
    metric: 'hit_rate_at_10',
    label: 'added product in the top 10',
  },
}

const PERCENT_METRICS = new Set([
  'wape_totals',
  'fast_pick_share',
  'pick_time_reduction',
  'hit_rate_at_10',
])

function metricValue(name: string, value: number | undefined): string {
  if (value === undefined) return '—'
  return PERCENT_METRICS.has(name) ? formatProbability(value) : value.toFixed(3)
}

/**
 * The model each use case uses, how it did on the most recent period it was tested on,
 * and when it last made predictions. Baselines are marked: a network is only used when
 * it beat the simple method.
 */
export function ModelsTable({ models }: { models: ModelSummary[] }) {
  if (models.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No trained models yet. Train them with <code>python scripts/train_models.py</code>, then
        score with <code>python scripts/score_models.py</code>.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Models in use</caption>
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            <th scope="col" className="py-2 pr-3 font-medium">
              Use case
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Model in use
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Test result
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Predictions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {models.map((model) => {
            const info = USE_CASES[model.use_case] ?? {
              title: model.use_case,
              metric: '',
              label: '',
            }
            return (
              <tr key={model.use_case} className="align-top">
                <th scope="row" className="py-2 pr-3 text-left font-medium">
                  {info.title}
                </th>
                <td className="py-2 pr-3">
                  <span className="font-mono text-xs">{model.model_name}</span>{' '}
                  {model.is_baseline ? (
                    <Badge>Baseline</Badge>
                  ) : (
                    <Badge tone="info">Neural network</Badge>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <span className="font-semibold tabular-nums">
                    {metricValue(info.metric, model.test_metrics[info.metric])}
                  </span>{' '}
                  <span className="text-xs text-slate-500">{info.label}</span>
                </td>
                <td className="py-2 pr-3 text-xs text-slate-600">
                  {model.as_of
                    ? `${formatInteger(model.predictions)} as of ${formatShortDate(model.as_of)}`
                    : 'Not scored yet'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
