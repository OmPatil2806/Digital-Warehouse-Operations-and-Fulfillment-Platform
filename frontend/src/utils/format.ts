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
