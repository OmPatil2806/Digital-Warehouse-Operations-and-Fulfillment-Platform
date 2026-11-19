import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { DelayAccuracy, DemandAccuracy, PredictionCheck } from '../../types/ml'
import { formatInteger, formatShortDate } from '../../utils/format'
import { ChartCard } from '../dashboard/ChartCard'
import { ChartTooltip } from '../dashboard/ChartTooltip'
import { INK, MARKS, seriesColor } from '../dashboard/chartTheme'
import { RiskBadge } from './RiskBadge'
import { formatBias, formatShare, formatUnits, modelLabel } from './mlFormat'

const axisTick = { fill: INK.muted, fontSize: 12 }

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900 tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-slate-500">{hint}</dd>}
    </div>
  )
}

/** The forecast made on an earlier day against the units customers then ordered. */
export function DemandCheck({ demand }: { demand: DemandAccuracy }) {
  const data = demand.daily.map((d) => ({
    day: d.day,
    forecast: d.forecast_units,
    actual: d.actual_units,
  }))
  return (
    <section aria-labelledby="demand-check" className="space-y-3">
      <div>
        <h4 id="demand-check" className="font-medium text-slate-800">
          Demand forecast of {formatShortDate(demand.as_of)}
        </h4>
        <p className="text-xs text-slate-500">
          {modelLabel(demand.model_name, demand.is_baseline)} · {formatInteger(demand.products)}{' '}
          products · {demand.days_checked} of {demand.days_forecast} forecast days have passed (
          {formatShortDate(demand.first_day)} – {formatShortDate(demand.last_day)})
        </p>
      </div>
      <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Forecast error"
          value={formatShare(demand.period_error)}
          hint={
            `Of each product's ${demand.days_checked}-day total` +
            (demand.test_error !== null ? `; ${formatShare(demand.test_error)} in testing` : '')
          }
        />
        <Stat
          label="Error per product and day"
          value={formatShare(demand.daily_error)}
          hint="Single days are much harder to predict"
        />
        <Stat
          label="All products together"
          value={formatBias(demand.bias)}
          hint={`${formatUnits(demand.forecast_units)} forecast, ${formatUnits(demand.actual_units)} ordered`}
        />
        <Stat
          label="Inside the likely range"
          value={formatShare(demand.range_coverage)}
          hint="Of product-days; the range aims at about 80 %"
        />
      </dl>
      <ChartCard
        title="Forecast and orders per day"
        description="All products: the units forecast for each day and the units customers then ordered"
        table={{
          columns: ['Day', 'Forecast', 'Ordered'],
          rows: demand.daily.map((d) => [
            formatShortDate(d.day),
            formatUnits(d.forecast_units),
            formatUnits(d.actual_units),
          ]),
        }}
      >
        <div className="h-64">
          <ResponsiveContainer>
            <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
              <CartesianGrid stroke={INK.grid} vertical={false} />
              <XAxis
                dataKey="day"
                tickFormatter={formatShortDate}
                stroke={INK.baseline}
                tick={axisTick}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis stroke={INK.baseline} tick={axisTick} tickLine={false} axisLine={false} />
              <Tooltip
                content={
                  <ChartTooltip
                    formatLabel={(day) => formatShortDate(String(day))}
                    formatValue={(value) => formatUnits(Number(value))}
                  />
                }
                cursor={{ stroke: INK.baseline }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: INK.secondary }} />
              <Line
                name="Forecast"
                dataKey="forecast"
                legendType="plainline"
                stroke={seriesColor(0)}
                strokeWidth={MARKS.lineWidth}
                dot={false}
                activeDot={{ r: MARKS.markerRadius, stroke: INK.surface, strokeWidth: 2 }}
                isAnimationActive={false}
              />
              <Line
                name="Ordered"
                dataKey="actual"
                legendType="plainline"
                stroke={seriesColor(1)}
                strokeWidth={MARKS.lineWidth}
                dot={false}
                activeDot={{ r: MARKS.markerRadius, stroke: INK.surface, strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>
    </section>
  )
}

/** The delivery risks given on an earlier day against when the parcels then arrived. */
export function DelayCheck({ delay }: { delay: DelayAccuracy }) {
  return (
    <section aria-labelledby="delay-check" className="space-y-3">
      <div>
        <h4 id="delay-check" className="font-medium text-slate-800">
          Delivery risks of {formatShortDate(delay.as_of)}
        </h4>
        <p className="text-xs text-slate-500">
          {modelLabel(delay.model_name, delay.is_baseline)} · {formatInteger(delay.parcels)} parcels
          were on their way
        </p>
      </div>
      <p className="text-sm text-slate-700">
        {formatInteger(delay.late)} of {formatInteger(delay.delivered)} delivered parcels arrived
        late ({formatShare(delay.late_rate)}). The model had marked{' '}
        {formatShare(delay.late_flagged)} of the late ones as medium or high risk.
        {delay.on_the_way > 0 && ` ${formatInteger(delay.on_the_way)} are still on their way.`}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Late deliveries by predicted risk</caption>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th scope="col" className="py-2 pr-3 font-medium">
                Predicted risk
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Parcels
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Delivered
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Late
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Late share
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 tabular-nums">
            {delay.levels.map((level) => (
              <tr key={level.risk_level}>
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <RiskBadge level={level.risk_level} />
                </th>
                <td className="py-2 pr-3 text-right">{formatInteger(level.parcels)}</td>
                <td className="py-2 pr-3 text-right">{formatInteger(level.delivered)}</td>
                <td className="py-2 pr-3 text-right">{formatInteger(level.late)}</td>
                <td className="py-2 pr-3 text-right font-medium whitespace-nowrap">
                  {formatShare(level.late_rate)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        A useful model shows a higher late share for higher risk levels.
      </p>
    </section>
  )
}

/** Predictions vs reality: how the latest checkable predictions did. */
export function PredictionCheckView({ check }: { check: PredictionCheck }) {
  if (!check.demand && !check.delay) {
    return (
      <p className="py-6 text-center text-sm text-slate-500">
        Nothing to check yet: predictions are checked once the days they cover have passed. To check
        the models on the last 30 days now, run a backtest:{' '}
        <code>python scripts/score_models.py --backtest 30</code>
      </p>
    )
  }
  return (
    <div className="space-y-6">
      {check.demand && <DemandCheck demand={check.demand} />}
      {check.delay && <DelayCheck delay={check.delay} />}
    </div>
  )
}
