import { BrainCircuit } from 'lucide-react'

import { getDemandForecast, getMovement, getProductRecommendations, mlKeys } from '../../api/mlApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import { Badge, type BadgeTone } from '../common/Badge'
import { ForecastChart } from './ForecastChart'
import { RecommendationList } from './RecommendationList'

const MOVEMENT: Record<string, { tone: BadgeTone; label: string }> = {
  fast: { tone: 'info', label: 'Fast mover' },
  medium: { tone: 'neutral', label: 'Medium mover' },
  slow: { tone: 'neutral', label: 'Slow mover' },
}

/** A product page's ML section: demand forecast, movement class and related products. */
export function ProductMLPanel({ productId }: { productId: number }) {
  const forecast = useApiQuery(mlKeys.forecast(productId), () => getDemandForecast(productId))
  // A product without a class answers 404: simply nothing to show.
  const movement = useApiQuery(mlKeys.movement(productId), () => getMovement(productId))
  const related = useApiQuery(mlKeys.recommendations(productId), () =>
    getProductRecommendations(productId),
  )
  const moving = movement.data ? MOVEMENT[movement.data.movement_class] : undefined

  return (
    <section aria-labelledby="ml-product-heading" className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="ml-product-heading" className="flex items-center gap-2 font-medium">
          <BrainCircuit size={16} aria-hidden="true" /> Forecast and insights
        </h2>
        {moving && movement.data && (
          <span className="flex items-center gap-2 text-sm text-slate-600">
            <Badge tone={moving.tone}>{moving.label}</Badge>
            {movement.data.picks_per_day.toFixed(2)} picks/day recently
          </span>
        )}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 lg:col-span-2">
          <ForecastChart
            forecast={forecast.data}
            isLoading={forecast.isPending}
            errorMessage={forecast.errorMessage}
          />
        </div>
        <section
          aria-labelledby="related-heading"
          className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <h3 id="related-heading" className="mb-3 font-medium text-slate-800">
            Frequently bought together
          </h3>
          {related.errorMessage ? (
            <p role="alert" className="text-sm text-red-700">
              {related.errorMessage}
            </p>
          ) : (
            <RecommendationList recommendations={related.data} />
          )}
        </section>
      </div>
    </section>
  )
}
