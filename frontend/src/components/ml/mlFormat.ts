/** Display helpers for ML predictions. */

/** 0.62 -> "62 %"; small risks keep one decimal ("3.4 %"). */
export function formatProbability(value: number): string {
  const percent = value * 100
  const text = percent < 10 ? Number(percent.toFixed(1)) : Math.round(percent)
  return `${text.toLocaleString('en-IE')} %`
}

/** Seconds of work per day as the reader thinks of them: "45 s", "6 min", "1.5 h" a day. */
export function formatSecondsPerDay(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${Math.round(seconds)} s/day`
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.round(minutes)} min/day`
  return `${Number((minutes / 60).toFixed(1)).toLocaleString('en-IE')} h/day`
}

/** Units with sensible precision: 0.4 -> "0.4", 12.6 -> "13". */
export function formatUnits(value: number): string {
  const rounded = value < 10 ? Number(value.toFixed(1)) : Math.round(value)
  return rounded.toLocaleString('en-IE')
}

/** Which model made a prediction, in words: "LSTM model" or "baseline: ABC analysis". */
export function modelLabel(name: string, isBaseline: boolean): string {
  const nice = name.replaceAll('_', ' ')
  return isBaseline ? `baseline: ${nice}` : `${nice} model`
}

/** How far a forecast was off on the whole: 0.04 -> "4 % too high", -0.1 -> "10 % too low". */
export function formatBias(value: number | null): string {
  if (value === null) return '—'
  if (Math.abs(value) < 0.005) return 'on target'
  return `${formatProbability(Math.abs(value))} too ${value > 0 ? 'high' : 'low'}`
}

/** A share that may be unknown (nothing to divide by). */
export function formatShare(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : formatProbability(value)
}
