import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { ChartCard, type ChartTable } from './ChartCard'
import { ChartTooltip } from './ChartTooltip'
import { INK, MARKS, seriesColor } from './chartTheme'

export interface BarSeries {
  key: string
  name: string
}

const BAR = 14 // px per bar
const CHAR = 7.5 // generous average width of a 12 px character

function textWidth(text: string): number {
  return Math.ceil(text.length * CHAR)
}
const GROUP_GAP = 14 // px between rows

/**
 * Horizontal bars, one row per item (zones, suppliers, categories, ...).
 * One series: values printed at the bar ends, no legend. Several series: grouped bars
 * in the fixed colour order with a legend, values in the tooltip and the table view.
 */
export function BarListChart<Row extends { label: string }>({
  title,
  description,
  rows,
  series,
  formatValue = (value) => String(value),
  domainMax,
  table,
  isLoading,
  isRefreshing,
  errorMessage,
  emptyMessage,
}: {
  title: string
  description?: string
  rows: Row[]
  series: BarSeries[]
  formatValue?: (value: number) => string
  /** Fixed end of the value axis, e.g. 100 for percentages. */
  domainMax?: number
  table: ChartTable
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
  emptyMessage?: string
}) {
  const single = series.length === 1
  const height = Math.max(120, rows.length * (series.length * BAR + GROUP_GAP) + (single ? 8 : 48))
  // Room for the longest category name and (one series) the longest printed value.
  const labelWidth = Math.min(200, Math.max(60, ...rows.map((r) => textWidth(r.label) + 24)))
  const valueWidth = single
    ? Math.max(
        24,
        ...rows.map((r) => textWidth(formatValue(Number(r[series[0].key as keyof Row]))) + 12),
      )
    : 16
  return (
    <ChartCard
      title={title}
      description={description}
      table={table}
      isLoading={isLoading}
      isRefreshing={isRefreshing}
      errorMessage={errorMessage}
      emptyMessage={emptyMessage}
    >
      <div style={{ height }}>
        <ResponsiveContainer>
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 0, right: valueWidth, bottom: 0, left: 0 }}
            barGap={MARKS.gap}
            barCategoryGap={GROUP_GAP / 2}
          >
            {!single && <CartesianGrid stroke={INK.grid} horizontal={false} />}
            <XAxis
              type="number"
              domain={[0, domainMax ?? 'auto']}
              tickFormatter={(v: number) => formatValue(v)}
              tick={{ fill: INK.muted, fontSize: 12 }}
              stroke={INK.baseline}
              tickLine={false}
              hide={single}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={labelWidth}
              tick={{ fill: INK.secondary, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: INK.baseline }}
            />
            <Tooltip
              content={<ChartTooltip formatValue={(v) => formatValue(Number(v))} />}
              cursor={{ fill: INK.grid, opacity: 0.4 }}
            />
            {!single && (
              <Legend
                iconType="rect"
                itemSorter={null}
                wrapperStyle={{ fontSize: 12, color: INK.secondary }}
              />
            )}
            {series.map((s, index) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                fill={seriesColor(index)}
                barSize={BAR}
                radius={[0, MARKS.barRadius, MARKS.barRadius, 0]}
                isAnimationActive={false}
              >
                {single && (
                  <LabelList
                    dataKey={s.key}
                    position="right"
                    // non-breaking spaces: SVG labels would otherwise wrap at "100 %"
                    formatter={(v: unknown) => formatValue(Number(v)).replaceAll(' ', '\u00a0')}
                    style={{ fill: INK.primary, fontSize: 12 }}
                  />
                )}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  )
}
