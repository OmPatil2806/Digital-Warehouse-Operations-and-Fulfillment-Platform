/** One entry of a Recharts tooltip payload (only the fields used here). */
export interface TooltipEntry {
  name?: string | number
  value?: string | number | readonly (string | number)[]
  color?: string
  dataKey?: string | number | ((data: never) => unknown)
}

/**
 * Tooltip content for Recharts (`<Tooltip content={<ChartTooltip ... />} />`).
 * The value leads in strong ink; the series name follows, keyed by a short line in the
 * series colour. Every series at the hovered position is listed.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  formatLabel = (value) => String(value),
  formatValue = (value) => String(value),
}: {
  active?: boolean
  payload?: readonly TooltipEntry[]
  label?: string | number
  formatLabel?: (label: string | number) => string
  formatValue?: (value: string | number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
      {label !== undefined && <p className="mb-1 text-slate-500">{formatLabel(label)}</p>}
      <ul className="space-y-0.5">
        {payload.map((entry) => (
          <li key={String(entry.name ?? entry.dataKey)} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-0.5 w-3 rounded"
              style={{ backgroundColor: entry.color }}
            />
            <span className="font-semibold text-slate-900 tabular-nums">
              {Array.isArray(entry.value)
                ? entry.value.map((v) => formatValue(v)).join(' – ')
                : formatValue(entry.value as string | number)}
            </span>
            <span className="text-slate-500">{entry.name}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
