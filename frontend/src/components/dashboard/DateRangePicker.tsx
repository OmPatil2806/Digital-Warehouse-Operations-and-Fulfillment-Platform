import { Check } from 'lucide-react'
import { useId, useState } from 'react'

import { Button } from '../common/Button'
import { TextField } from '../form/fields'
import { RANGE_PRESETS, rangeError, todayUtc, type DateRangeValue } from './dateRange'

/** Date range for a whole dashboard: presets first, a custom range behind them. */
export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRangeValue
  onChange: (value: DateRangeValue) => void
}) {
  const groupId = useId()
  const [custom, setCustom] = useState(value.preset === 'custom')
  const [from, setFrom] = useState(value.from)
  const [to, setTo] = useState(value.to || todayUtc())
  const [error, setError] = useState<string | null>(null)

  const apply = () => {
    const problem = rangeError(from, to)
    setError(problem)
    if (!problem) onChange({ preset: 'custom', from, to })
  }

  const option = (selected: boolean) =>
    `flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm ${
      selected
        ? 'border-blue-600 bg-blue-50 font-semibold text-blue-800'
        : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
    }`

  return (
    <div className="space-y-3">
      <div role="group" aria-labelledby={groupId} className="flex flex-wrap items-center gap-2">
        <span id={groupId} className="text-sm font-medium text-slate-700">
          Period
        </span>
        {RANGE_PRESETS.map((preset) => {
          const selected = !custom && value.preset === preset.value
          return (
            <button
              key={preset.value}
              type="button"
              aria-pressed={selected}
              className={option(selected)}
              onClick={() => {
                setCustom(false)
                setError(null)
                onChange({ preset: preset.value, from: '', to: '' })
              }}
            >
              {selected && <Check size={16} strokeWidth={3} aria-hidden="true" />}
              {preset.label}
            </button>
          )
        })}
        <button
          type="button"
          aria-pressed={custom}
          aria-expanded={custom}
          className={option(custom)}
          onClick={() => setCustom(true)}
        >
          {custom && <Check size={16} strokeWidth={3} aria-hidden="true" />}
          Custom range
        </button>
      </div>
      {custom && (
        <div className="flex flex-wrap items-end gap-3 border-t border-slate-200 pt-3">
          <TextField
            label="From"
            type="date"
            value={from}
            max={to || undefined}
            onChange={(event) => setFrom(event.target.value)}
          />
          <TextField
            label="To"
            type="date"
            value={to}
            min={from || undefined}
            onChange={(event) => setTo(event.target.value)}
          />
          <Button variant="secondary" onClick={apply}>
            Apply
          </Button>
          {error && (
            <p role="alert" className="w-full text-sm text-red-700">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
