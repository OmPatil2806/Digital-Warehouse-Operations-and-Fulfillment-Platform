import { CheckCircle2, Search, X } from 'lucide-react'
import { useId, useState } from 'react'

import { getErrorMessage } from '../../api/apiClient'
import { catalogKeys, listProducts } from '../../api/catalogApi'
import { checkFit, getBinByCode, warehouseKeys } from '../../api/warehouseApi'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { InventoryRow, ProductRef } from '../../types/inventory'
import type { BinDetail } from '../../types/warehouse'
import { formatNumber } from '../../utils/format'
import { TextField } from '../form/fields'

const labelClass = 'block text-sm font-medium text-slate-700'

// ------------------------------------------------------------------- product
/** Search a product by SKU or name and pick it from the matches. */
export function ProductPicker({
  value,
  onChange,
  error,
}: {
  value: ProductRef | null
  onChange: (product: ProductRef | null) => void
  error?: string
}) {
  const [text, setText] = useState('')
  const id = useId()
  const q = text.trim()
  const matches = useApiQuery(
    [...catalogKeys.products, 'picker', q],
    () => listProducts({ q, status: 'active', limit: 6 }),
    { enabled: !value && q.length >= 2 },
  )

  if (value) {
    return (
      <div>
        <p className={labelClass}>Product</p>
        <div className="mt-1 flex items-center justify-between rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm">
          <span>
            <span className="font-mono text-xs">{value.sku}</span> · {value.name}
          </span>
          <button
            type="button"
            onClick={() => onChange(null)}
            aria-label="Change product"
            className="rounded p-1 text-slate-500 hover:bg-slate-200"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        Product{' '}
        <span className="text-red-600" aria-hidden="true">
          *
        </span>
      </label>
      <div className="relative mt-1">
        <Search
          size={14}
          aria-hidden="true"
          className="absolute top-1/2 left-3 -translate-y-1/2 text-slate-400"
        />
        <input
          id={id}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Type a SKU or name"
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`block w-full rounded-lg border bg-white py-2 pr-3 pl-8 text-sm shadow-sm outline-none focus:border-blue-600 ${error ? 'border-red-400' : 'border-slate-300'}`}
        />
      </div>
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
      {q.length >= 2 && (
        <ul
          aria-label="Matching products"
          className="mt-1 divide-y divide-slate-100 rounded-lg border border-slate-200"
        >
          {matches.isPending && <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>}
          {matches.data?.items.length === 0 && (
            <li className="px-3 py-2 text-xs text-slate-500">No active product matches.</li>
          )}
          {matches.data?.items.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => onChange({ id: p.id, sku: p.sku, name: p.name })}
                className="w-full px-3 py-2 text-left text-sm hover:bg-blue-50"
              >
                <span className="font-mono text-xs">{p.sku}</span> · {p.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ----------------------------------------------------------------------- bin
/** Type (or scan) a location code; the bin is looked up when the field is left or on Enter. */
export function BinCodeField({
  label,
  value,
  onChange,
  error,
}: {
  label: string
  value: BinDetail | null
  onChange: (bin: BinDetail | null) => void
  error?: string
}) {
  const [text, setText] = useState(value?.location_code ?? '')
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const lookup = async () => {
    const code = text.trim().toUpperCase()
    if (!code || code === value?.location_code) return
    setChecking(true)
    try {
      const bin = await getBinByCode(code)
      setText(bin.location_code)
      setLookupError(bin.is_active ? null : 'This bin is archived')
      onChange(bin.is_active ? bin : null)
    } catch (err) {
      setLookupError(
        getErrorMessage(err) === 'Bin not found' ? 'No bin with this code' : getErrorMessage(err),
      )
      onChange(null)
    } finally {
      setChecking(false)
    }
  }

  const hint = value
    ? `${value.warehouse.code} · ${value.zone.name} (${value.zone.zone_type}) · shelf level ${value.shelf.level}`
    : checking
      ? 'Looking up…'
      : 'e.g. WH01-ZA-R01-S01-B01 — press Enter or leave the field to look it up'

  return (
    <TextField
      label={label}
      required
      value={text}
      placeholder="WH01-ZA-R01-S01-B01"
      onChange={(event) => {
        setText(event.target.value)
        if (value) onChange(null)
      }}
      onBlur={() => void lookup()}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          void lookup()
        }
      }}
      error={lookupError ?? error}
      hint={hint}
    />
  )
}

/** Choose one of the bins that hold the product (for moving or correcting stock). */
export function SourceBinSelect({
  label,
  rows,
  value,
  onChange,
  describe,
  error,
}: {
  label: string
  rows: InventoryRow[] | undefined
  value: number | null
  onChange: (binId: number | null) => void
  describe: (row: InventoryRow) => string
  error?: string
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={labelClass}>
        {label}{' '}
        <span className="text-red-600" aria-hidden="true">
          *
        </span>
      </label>
      <select
        id={id}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
        aria-invalid={error ? 'true' : 'false'}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-sm shadow-sm ${error ? 'border-red-400' : 'border-slate-300'}`}
      >
        <option value="">
          {rows === undefined
            ? 'Loading bins…'
            : rows.length
              ? 'Choose a bin'
              : 'No stock in any bin'}
        </option>
        {rows?.map((row) => (
          <option key={row.bin.id} value={row.bin.id}>
            {row.bin.location_code} — {describe(row)}
          </option>
        ))}
      </select>
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ capacity
/** Live check: do `quantity` more units fit into the bin, on top of what it holds? */
export function FitHint({
  binId,
  productId,
  quantity,
}: {
  binId: number | undefined
  productId: number | undefined
  quantity: number
}) {
  const ready = binId !== undefined && productId !== undefined && quantity >= 1
  const fit = useApiQuery(
    [...warehouseKeys.all, 'fit', binId, productId, quantity],
    () => checkFit(binId ?? 0, productId ?? 0, quantity),
    { enabled: ready },
  )
  if (!ready || !fit.data) return null
  const f = fit.data
  if (!f.fits) {
    return (
      <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
        Does not fit: {f.reasons.join('; ')}
      </p>
    )
  }
  const after = Number(f.used_weight_kg) + Number(f.required_weight_kg)
  return (
    <p className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
      <CheckCircle2 size={16} aria-hidden="true" />
      Fits: {formatNumber(after, 'kg')} of {formatNumber(f.max_weight_kg, 'kg')} after this
    </p>
  )
}
