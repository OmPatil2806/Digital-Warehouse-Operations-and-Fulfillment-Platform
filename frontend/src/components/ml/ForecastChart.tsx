import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { DemandForecast } from '../../types/ml'
import { formatShortDate } from '../../utils/format'
import { ChartCard } from '../dashboard/ChartCard'
import { ChartTooltip } from '../dashboard/ChartTooltip'
import { INK, MARKS, seriesColor } from '../dashboard/chartTheme'
import { formatUnits } from './mlFormat'
import { ScoringNote } from './ScoringNote'

const axisTick = { fill: INK.muted, fontSize: 12 }

/**
 * Expected units per day for the coming days (line) and the range the actual demand
 * falls in on about 8 of 10 days (band). Totals for 7, 14 and 30 days below.
 */
export function ForecastChart({
  forecast,
  isLoading,
  errorMessage,
}: {
  forecast: DemandForecast | undefined
  isLoading?: boolean
  errorMessage?: string | null
}) {
  const days = forecast?.days ?? []
  const data = days.map((d) => ({
    day: d.day,
    expected: d.expected_units,
    range: [d.low_units, d.high_units],
  }))
  return (
    <ChartCard
      title="Demand forecast"
      description="Expected units per day, with the range for about 8 days in 10"
      isLoading={isLoading}
      errorMessage={errorMessage}
      emptyMessage="No forecast yet: the models have not scored this product."
      table={{
        columns: ['Day', 'Expected', 'Low', 'High'],
        rows: days.map((d) => [
          formatShortDate(d.day),
          formatUnits(d.expected_units),
          formatUnits(d.low_units),
          formatUnits(d.high_units),
        ]),
      }}
    >
      <div className="h-64">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
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
            <Area
              name="Likely range"
              dataKey="range"
              legendType="square"
              stroke="none"
              fill={seriesColor(0)}
              fillOpacity={0.15}
              isAnimationActive={false}
            />
            <Line
              name="Expected units"
              dataKey="expected"
              legendType="plainline"
              stroke={seriesColor(0)}
              strokeWidth={MARKS.lineWidth}
              dot={false}
              activeDot={{ r: MARKS.markerRadius, stroke: INK.surface, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {forecast && forecast.totals.length > 0 && (
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
          {forecast.totals.map((total) => (
            <div key={total.days} className="rounded-lg bg-slate-50 px-2 py-2">
              <dt className="text-xs text-slate-500">Next {total.days} days</dt>
              <dd className="text-lg font-semibold text-slate-900 tabular-nums">
                {formatUnits(total.expected_units)}
                <span className="ml-1 text-xs font-normal text-slate-500">units</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-2">
        <ScoringNote scoring={forecast?.scoring} />
      </div>
    </ChartCard>
  )
}
