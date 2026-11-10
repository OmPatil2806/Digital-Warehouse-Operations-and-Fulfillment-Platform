import type { SupplierKpi } from '../../types/dashboard'
import { formatDays } from '../../utils/format'
import { BarListChart } from './BarListChart'

const SERIES = [
  { key: 'promised', name: 'Promised lead time' },
  { key: 'actual', name: 'Actual (average)' },
]

/** Promised against actual lead time, for suppliers with deliveries in the period. */
export function SupplierChart({
  suppliers,
  isLoading,
  isRefreshing,
  errorMessage,
}: {
  suppliers: SupplierKpi[] | undefined
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
}) {
  const delivered = (suppliers ?? []).filter((s) => s.lead_time_avg_days !== null)
  return (
    <BarListChart
      title="Lead time: promised and actual"
      description="Days from ordering to full receipt, for purchase orders received in the period"
      rows={delivered.map((s) => ({
        label: s.code,
        promised: s.promised_lead_time_days,
        actual: Number(s.lead_time_avg_days),
      }))}
      series={SERIES}
      formatValue={(v) => formatDays(v)}
      isLoading={isLoading}
      isRefreshing={isRefreshing}
      errorMessage={errorMessage}
      emptyMessage="No purchase order was fully received in this period."
      table={{
        columns: ['Supplier', ...SERIES.map((s) => s.name), 'Variation (std. dev.)'],
        rows: delivered.map((s) => [
          `${s.code} · ${s.name}`,
          formatDays(s.promised_lead_time_days),
          formatDays(s.lead_time_avg_days),
          formatDays(s.lead_time_stddev_days),
        ]),
      }}
    />
  )
}
