import { getOrderDelayRisk, mlKeys } from '../../api/mlApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import { formatShortDate } from '../../utils/format'
import { RiskBadge } from './RiskBadge'

/** Delay risk of an order's shipment while it is on its way (nothing otherwise). */
export function OrderDelayRisk({ orderId }: { orderId: number }) {
  const query = useApiQuery(mlKeys.delayRisk(orderId), () => getOrderDelayRisk(orderId))
  const prediction = query.data?.prediction
  if (!prediction) return null
  return (
    <section
      aria-labelledby="delay-risk-heading"
      className="flex flex-wrap items-start gap-x-4 gap-y-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <h2 id="delay-risk-heading" className="font-medium">
        Delivery risk
      </h2>
      <RiskBadge level={prediction.risk_level} probability={prediction.probability} />
      <p className="text-sm text-slate-600">
        {prediction.reasons.length
          ? `Main reasons: ${prediction.reasons.join('; ')}`
          : 'No particular risk factor.'}
      </p>
      <p className="basis-full text-xs text-slate-500">
        As of {formatShortDate(prediction.as_of)}: an early warning, not a certainty.
      </p>
    </section>
  )
}
