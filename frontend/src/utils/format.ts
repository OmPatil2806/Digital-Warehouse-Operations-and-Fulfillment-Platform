/** Display helpers. Decimals arrive from the API as exact strings such as "899.99". */

const money = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })
const integer = new Intl.NumberFormat('en-IE', { maximumFractionDigits: 0 })

export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return money.format(Number(value))
}

export function formatNumber(value: string | number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = Number(value).toLocaleString('en-IE', { maximumFractionDigits: 3 })
  return unit ? `${text} ${unit}` : text
}

export function formatInteger(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return integer.format(Number(value))
}

/** "0.95" -> "95 %" */
export function formatPercent(value: string | number): string {
  return `${Math.round(Number(value) * 100)} %`
}

export function formatDimensions(length: string, width: string, height: string): string {
  return `${formatNumber(length)} × ${formatNumber(width)} × ${formatNumber(height)} cm`
}

// ------------------------------------------------------------------ dashboards
/** An API percentage such as "66.7" -> "66.7 %". */
export function formatPercentage(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return `${Number(value).toLocaleString('en-IE', { maximumFractionDigits: 1 })} %`
}

/** Hours as the reader thinks of them: "45 min", "6.5 h", "22 h" or "4.5 days". */
export function formatHours(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const hours = Number(value)
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 10) return `${Number(hours.toFixed(1))} h`
  if (hours < 48) return `${Math.round(hours)} h`
  return formatDays(hours / 24)
}

/** "4.0" -> "4 days", "1" -> "1 day", "2.25" -> "2.3 days". */
export function formatDays(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const days = Number(Number(value).toFixed(1))
  return `${days.toLocaleString('en-IE')} ${days === 1 ? 'day' : 'days'}`
}

const shortDate = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  timeZone: 'UTC',
})

/** A calendar day from the API ("2026-11-07") as a short axis label: "7 Nov". */
export function formatShortDate(day: string): string {
  return shortDate.format(new Date(`${day}T00:00:00Z`))
}

/** "1 product", "2 products"; pass the plural when it is not word + "s". */
export function plural(count: number | null | undefined, word: string, many = `${word}s`): string {
  return `${formatInteger(count)} ${count === 1 ? word : many}`
}
