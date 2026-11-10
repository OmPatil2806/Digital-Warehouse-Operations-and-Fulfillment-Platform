/** CSV files for spreadsheets and analysis tools (RFC 4180: comma-separated, CRLF lines). */

export type CsvCell = string | number | boolean | null | undefined

export interface CsvTable {
  columns: string[]
  rows: CsvCell[][]
}

// A cell starting like a formula would be run by Excel ("=HYPERLINK(...)"): CSV injection.
const FORMULA_START = /^[=+\-@\t\r]/

/** One cell: quoted when needed, formulas neutralised. Numbers stay plain. */
export function csvCell(value: CsvCell): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  let text = String(value)
  if (FORMULA_START.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) text = `'${text}`
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function toCsv({ columns, rows }: CsvTable): string {
  return [columns, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

/** Let the browser save the table as a file. The BOM makes Excel read UTF-8 (€, ü, ²). */
export function downloadCsv(filename: string, table: CsvTable): void {
  const blob = new Blob(['﻿', toCsv(table)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

/** "inventory-report_2026-10-12_2026-11-10.csv" */
export function csvFilename(name: string, dateFrom?: string, dateTo?: string): string {
  return `${[name, dateFrom, dateTo].filter(Boolean).join('_')}.csv`
}
