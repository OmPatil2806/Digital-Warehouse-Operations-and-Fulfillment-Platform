import type { DateRangeParams } from '../../types/dashboard'

/** The API counts in UTC days; so do the presets. */
export const MAX_RANGE_DAYS = 366

export const RANGE_PRESETS = [
  { value: '7', label: 'Last 7 days', days: 7 },
  { value: '30', label: 'Last 30 days', days: 30 },
  { value: '90', label: 'Last 90 days', days: 90 },
] as const

export type RangePreset = (typeof RANGE_PRESETS)[number]['value'] | 'custom'

export interface DateRangeValue {
  preset: RangePreset
  from: string // ISO day, only for "custom"
  to: string
}

export const DEFAULT_RANGE: DateRangeValue = { preset: '30', from: '', to: '' }

export function todayUtc(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10)
}

function addDays(day: string, days: number): string {
  const date = new Date(`${day}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000)
}

/** The request parameters for a picker value (both days included). */
export function rangeParams(value: DateRangeValue, today: string = todayUtc()): DateRangeParams {
  if (value.preset === 'custom') return { date_from: value.from, date_to: value.to }
  const preset = RANGE_PRESETS.find((p) => p.value === value.preset) ?? RANGE_PRESETS[1]
  return { date_from: addDays(today, 1 - preset.days), date_to: today }
}

/** Why a custom range cannot be used, or null when it is fine. Mirrors the API rules. */
export function rangeError(from: string, to: string): string | null {
  if (!from || !to) return 'Choose a start and an end date'
  if (from > to) return 'The start date must not be after the end date'
  if (daysBetween(from, to) + 1 > MAX_RANGE_DAYS) return `Choose at most ${MAX_RANGE_DAYS} days`
  return null
}
