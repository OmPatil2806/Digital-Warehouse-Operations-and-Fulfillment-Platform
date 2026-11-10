import type { ZoneUse } from '../../types/dashboard'
import { formatPercentage } from '../../utils/format'
import { BarListChart } from './BarListChart'

const SERIES = [
  { key: 'bins', name: 'Bins in use' },
  { key: 'weight', name: 'Weight used' },
  { key: 'volume', name: 'Volume used' },
]

const pct = (value: string | null) => (value === null ? 0 : Number(value))

/** How full each zone is: share of bins in use, and of weight and volume capacity. */
export function OccupancyChart({
  zones,
  isLoading,
  isRefreshing,
  errorMessage,
}: {
  zones: ZoneUse[] | undefined
  isLoading?: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
}) {
  const withBins = (zones ?? []).filter((z) => z.bins > 0)
  const rows = withBins.map((z) => ({
    label: `${z.code} · ${z.name}`,
    bins: pct(z.occupancy_percent),
    weight: pct(z.weight_percent),
    volume: pct(z.volume_percent),
  }))
  return (
    <BarListChart
      title="Zone use"
      description="Share of active bins holding stock, and of their weight and volume limits"
      rows={rows}
      series={SERIES}
      domainMax={100}
      formatValue={(v) => formatPercentage(v)}
      isLoading={isLoading}
      isRefreshing={isRefreshing}
      errorMessage={errorMessage}
      emptyMessage="No zones with active bins yet."
      table={{
        columns: ['Zone', ...SERIES.map((s) => s.name)],
        rows: withBins.map((z) => [
          `${z.code} · ${z.name}`,
          formatPercentage(z.occupancy_percent),
          formatPercentage(z.weight_percent),
          formatPercentage(z.volume_percent),
        ]),
      }}
    />
  )
}
