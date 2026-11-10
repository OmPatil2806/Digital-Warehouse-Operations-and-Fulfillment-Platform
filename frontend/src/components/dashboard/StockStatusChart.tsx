import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { InventoryDashboard, StockStatus } from '../../types/dashboard'
import { ChartCard } from './ChartCard'
import { ChartTooltip } from './ChartTooltip'
import { INK, MARKS } from './chartTheme'
import { STOCK_STATUS, stockStatusColor } from './dashboardFormat'

const ORDER: StockStatus[] = ['ok', 'low', 'out']

/** Active products by availability: in stock, below minimum, out of stock. */
export function StockStatusChart({
  counts,
  isLoading,
  isRefreshing,
  errorMessage,
}: {
  counts: InventoryDashboard['stock_status'] | undefined
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
}) {
  const rows = counts
    ? ORDER.map((status) => ({
        status,
        label: STOCK_STATUS[status].label,
        products: counts[status],
      }))
    : []
  const total = rows.reduce((sum, r) => sum + r.products, 0)
  return (
    <ChartCard
      title="Stock status"
      description={`${total} active products by what is available now`}
      isLoading={isLoading}
      isRefreshing={isRefreshing}
      errorMessage={errorMessage}
      emptyMessage="No active products yet."
      table={{
        columns: ['Status', 'Products'],
        rows: total ? rows.map((r) => [r.label, r.products]) : [],
      }}
    >
      <div className="h-44">
        <ResponsiveContainer>
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 0, right: 40, bottom: 0, left: 8 }}
            barCategoryGap={MARKS.gap * 6}
          >
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="label"
              width={110}
              tick={{ fill: INK.secondary, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: INK.baseline }}
            />
            <Tooltip
              content={<ChartTooltip formatValue={(v) => `${v} products`} />}
              cursor={{ fill: INK.grid, opacity: 0.4 }}
            />
            <Bar
              dataKey="products"
              name="Products"
              barSize={18}
              radius={[0, MARKS.barRadius, MARKS.barRadius, 0]}
              isAnimationActive={false}
            >
              {rows.map((row) => (
                <Cell key={row.status} fill={stockStatusColor(row.status)} />
              ))}
              <LabelList
                dataKey="products"
                position="right"
                style={{ fill: INK.primary, fontSize: 12 }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  )
}
