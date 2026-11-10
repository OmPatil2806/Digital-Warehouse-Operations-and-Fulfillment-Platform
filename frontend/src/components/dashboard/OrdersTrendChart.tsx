import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { FulfillmentDashboard } from '../../types/dashboard'
import { formatShortDate } from '../../utils/format'
import { ChartCard } from './ChartCard'
import { ChartTooltip } from './ChartTooltip'
import { INK, MARKS, seriesColor } from './chartTheme'

const SERIES = [
  { key: 'placed', name: 'Placed' },
  { key: 'shipped', name: 'Shipped' },
  { key: 'delivered', name: 'Delivered' },
] as const

const axisTick = { fill: INK.muted, fontSize: 12 }

/** Orders placed, shipped and delivered per day of the period. */
export function OrdersTrendChart({
  perDay,
  isLoading,
  isRefreshing,
  errorMessage,
}: {
  perDay: FulfillmentDashboard['per_day'] | undefined
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
}) {
  const days = perDay ?? []
  const hasOrders = days.some((d) => d.placed || d.shipped || d.delivered)
  return (
    <ChartCard
      title="Orders per day"
      description="Placed, shipped and delivered, per day (UTC)"
      isLoading={isLoading}
      isRefreshing={isRefreshing}
      errorMessage={errorMessage}
      emptyMessage="No orders were placed, shipped or delivered in this period."
      table={{
        columns: ['Day', ...SERIES.map((s) => s.name)],
        rows: hasOrders
          ? days.map((d) => [formatShortDate(d.day), d.placed, d.shipped, d.delivered])
          : [],
      }}
    >
      <div className="h-72">
        <ResponsiveContainer>
          <LineChart data={days} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid stroke={INK.grid} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={formatShortDate}
              stroke={INK.baseline}
              tick={axisTick}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              stroke={INK.baseline}
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
            />
            <Tooltip
              content={<ChartTooltip formatLabel={(day) => formatShortDate(String(day))} />}
              cursor={{ stroke: INK.baseline }}
            />
            <Legend
              iconType="plainline"
              itemSorter={null} // keep the order of the status flow
              wrapperStyle={{ fontSize: 12, color: INK.secondary }}
            />
            {SERIES.map((series, index) => (
              <Line
                key={series.key}
                name={series.name}
                dataKey={series.key}
                stroke={seriesColor(index)}
                strokeWidth={MARKS.lineWidth}
                dot={days.length === 1 ? { r: MARKS.markerRadius } : false}
                activeDot={{ r: MARKS.markerRadius, stroke: INK.surface, strokeWidth: 2 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  )
}
