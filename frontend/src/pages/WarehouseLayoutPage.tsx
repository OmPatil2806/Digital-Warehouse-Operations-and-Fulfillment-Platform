import { AxiosError } from 'axios'
import {
  Archive,
  ArchiveRestore,
  Plus,
  ScanLine,
  Sparkles,
  Warehouse as WarehouseIcon,
} from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'

import { getErrorMessage } from '../api/apiClient'
import {
  getBinByCode,
  getLayout,
  listWarehouses,
  setRackActive,
  setZoneActive,
  warehouseKeys,
} from '../api/warehouseApi'
import { Badge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { BinDetailsDialog } from '../components/warehouse/BinDetailsDialog'
import { GenerateBinsDialog } from '../components/warehouse/GenerateBinsDialog'
import { LayoutGrid, OccupancyLegend } from '../components/warehouse/LayoutGrid'
import { WarehouseFormDialog, ZoneFormDialog } from '../components/warehouse/LayoutFormDialogs'
import { locateBin, type BinSelection } from '../components/warehouse/layoutUtils'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import type { LayoutRack, LayoutZone, Rack, WarehouseLayout, Zone } from '../types/warehouse'
import { formatInteger, formatNumber } from '../utils/format'
import { canEditMasterData } from '../utils/permissions'

const URL_DEFAULTS = { warehouse: '', zone: '', archived: '' }

const ZONE_TONES = {
  picking: 'info',
  bulk: 'neutral',
  cold: 'info',
  hazardous: 'danger',
  returns: 'warning',
} as const

type Pending = { kind: 'zone'; zone: LayoutZone } | { kind: 'rack'; rack: LayoutRack } | null

export default function WarehouseLayoutPage() {
  const { user } = useAuth()
  const canEdit = canEditMasterData(user)
  const [state, setState] = useUrlState(URL_DEFAULTS)
  const showArchived = state.archived === '1'

  const warehouses = useApiQuery(warehouseKeys.all, listWarehouses)
  const warehouseId = Number(state.warehouse) || warehouses.data?.[0]?.id
  const layout = useApiQuery(
    warehouseKeys.layout(warehouseId ?? 0, showArchived),
    () => getLayout(warehouseId!, showArchived),
    { enabled: warehouseId !== undefined },
  )

  const [selected, setSelected] = useState<BinSelection | null>(null)
  const [highlighted, setHighlighted] = useState<string | null>(null)
  const [generatingFor, setGeneratingFor] = useState<LayoutZone | null>(null)
  const [creatingWarehouse, setCreatingWarehouse] = useState(false)
  const [creatingZone, setCreatingZone] = useState(false)
  const [pending, setPending] = useState<Pending>(null)

  const zones = layout.data?.zones ?? []
  const zone = zones.find((z) => z.code === state.zone) ?? zones[0]

  const toggle = useApiMutation(
    (target: NonNullable<Pending>): Promise<Zone | Rack> =>
      target.kind === 'zone'
        ? setZoneActive(target.zone.id, !target.zone.is_active)
        : setRackActive(target.rack.id, !target.rack.is_active),
    {
      invalidates: [[...warehouseKeys.all, warehouseId]],
      successMessage: (r) => `${r.code} ${r.is_active ? 'restored' : 'archived'}`,
      onSuccess: () => setPending(null),
    },
  )

  // ------------------------------------------------------------------ empty states
  if (warehouses.isPending)
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading…
      </p>
    )
  if (warehouses.errorMessage) {
    return (
      <p role="alert" className="text-sm text-red-700">
        {warehouses.errorMessage}
      </p>
    )
  }
  if (!warehouses.data?.length) {
    return (
      <div className="mx-auto max-w-lg rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
        <WarehouseIcon size={32} className="mx-auto text-slate-400" aria-hidden="true" />
        <h1 className="mt-3 text-lg font-semibold">No warehouses yet</h1>
        <p className="mt-1 text-sm text-slate-500">
          {canEdit
            ? 'Create the first warehouse, then add zones and generate bins.'
            : 'An administrator or manager has to set up the warehouse first.'}
        </p>
        {canEdit && (
          <Button
            className="mt-5"
            icon={<Plus size={16} aria-hidden="true" />}
            onClick={() => setCreatingWarehouse(true)}
          >
            New warehouse
          </Button>
        )}
        <WarehouseFormDialog
          open={creatingWarehouse}
          onClose={() => setCreatingWarehouse(false)}
          onCreated={(w) => setState({ warehouse: String(w.id) })}
        />
      </div>
    )
  }

  const current = layout.data
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        title="Warehouse layout"
        description="Zones, racks, shelves and bins. Racks are ordered by walking distance to the packing station."
        actions={
          canEdit && (
            <Button
              variant="secondary"
              icon={<Plus size={16} aria-hidden="true" />}
              onClick={() => setCreatingWarehouse(true)}
            >
              New warehouse
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect
          label="Warehouse"
          value={String(warehouseId)}
          onChange={(id) => setState({ warehouse: id, zone: '' })}
          options={warehouses.data.map((w) => ({
            value: String(w.id),
            label: `${w.code} · ${w.name}`,
          }))}
        />
        <FindBin
          onFound={(code, zoneCode, foundWarehouseId) => {
            setState({ warehouse: String(foundWarehouseId), zone: zoneCode })
            setHighlighted(code)
          }}
        />
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setState({ archived: event.target.checked ? '1' : '' })}
            className="h-4 w-4 rounded border-slate-300"
          />
          Show archived
        </label>
      </div>

      {layout.isPending ? (
        <p role="status" className="text-sm text-slate-500">
          Loading layout…
        </p>
      ) : layout.errorMessage || !current ? (
        <p role="alert" className="text-sm text-red-700">
          {layout.errorMessage}
        </p>
      ) : (
        <>
          <Totals layout={current} />

          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200">
            <div role="tablist" aria-label="Zones" className="flex flex-wrap gap-1">
              {zones.map((z) => (
                <button
                  key={z.id}
                  role="tab"
                  type="button"
                  aria-selected={z.id === zone?.id}
                  onClick={() => setState({ zone: z.code })}
                  className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium ${
                    z.id === zone?.id
                      ? 'border-blue-600 text-blue-700'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  } ${z.is_active ? '' : 'opacity-60'}`}
                >
                  {z.code}
                  <span className="hidden font-normal sm:inline">{z.name}</span>
                </button>
              ))}
            </div>
            {canEdit && (
              <Button
                variant="ghost"
                size="sm"
                icon={<Plus size={14} aria-hidden="true" />}
                onClick={() => setCreatingZone(true)}
              >
                Add zone
              </Button>
            )}
          </div>

          {zone ? (
            <section role="tabpanel" aria-label={`Zone ${zone.code}`} className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
                  <Badge tone={ZONE_TONES[zone.zone_type]}>{zone.zone_type}</Badge>
                  {!zone.is_active && <Badge>archived</Badge>}
                  <span>
                    {formatInteger(zone.racks.length)} racks ·{' '}
                    {formatInteger(zone.totals.active_bins)} active bins ·{' '}
                    {formatNumber(zone.totals.max_weight_kg, 'kg')} ·{' '}
                    {formatInteger(zone.totals.max_volume_cm3 / 1_000_000)} m³
                  </span>
                </div>
                {canEdit && (
                  <div className="flex gap-2">
                    {zone.is_active && (
                      <Button
                        size="sm"
                        icon={<Sparkles size={14} aria-hidden="true" />}
                        onClick={() => setGeneratingFor(zone)}
                      >
                        Generate bins
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant={zone.is_active ? 'secondary' : 'primary'}
                      icon={
                        zone.is_active ? (
                          <Archive size={14} aria-hidden="true" />
                        ) : (
                          <ArchiveRestore size={14} aria-hidden="true" />
                        )
                      }
                      onClick={() => setPending({ kind: 'zone', zone })}
                    >
                      {zone.is_active ? 'Archive zone' : 'Restore zone'}
                    </Button>
                  </div>
                )}
              </div>
              <OccupancyLegend />
              <LayoutGrid
                racks={zone.racks}
                highlighted={highlighted}
                onSelectBin={(bin) => setSelected(locateBin(current, bin.location_code))}
                onToggleRack={canEdit ? (rack) => setPending({ kind: 'rack', rack }) : undefined}
              />
            </section>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              {showArchived || !canEdit
                ? 'This warehouse has no zones yet.'
                : 'No active zones. Add a zone to start.'}
            </p>
          )}
        </>
      )}

      <BinDetailsDialog
        selection={selected}
        warehouseCode={current?.code ?? ''}
        onClose={() => setSelected(null)}
      />
      {warehouseId !== undefined && (
        <GenerateBinsDialog
          zone={generatingFor}
          warehouseId={warehouseId}
          onClose={() => setGeneratingFor(null)}
        />
      )}
      <WarehouseFormDialog
        open={creatingWarehouse}
        onClose={() => setCreatingWarehouse(false)}
        onCreated={(w) => setState({ warehouse: String(w.id), zone: '' })}
      />
      <ZoneFormDialog
        warehouse={creatingZone && current ? current : null}
        onClose={() => setCreatingZone(false)}
        onCreated={(z) => setState({ zone: z.code })}
      />
      <ConfirmDialog
        open={pending !== null}
        title={pendingTitle(pending)}
        message={pendingMessage(pending)}
        confirmLabel={pending && isActive(pending) ? 'Archive' : 'Restore'}
        tone={pending && isActive(pending) ? 'danger' : 'primary'}
        loading={toggle.isPending}
        onConfirm={() => pending && toggle.mutate(pending)}
        onCancel={() => setPending(null)}
      />
    </div>
  )
}

function isActive(pending: NonNullable<Pending>): boolean {
  return pending.kind === 'zone' ? pending.zone.is_active : pending.rack.is_active
}

function pendingTitle(pending: Pending): string {
  if (!pending) return ''
  const code = pending.kind === 'zone' ? pending.zone.code : pending.rack.code
  return `${isActive(pending) ? 'Archive' : 'Restore'} ${pending.kind} ${code}?`
}

function pendingMessage(pending: Pending): string {
  if (!pending) return ''
  if (!isActive(pending)) {
    return `Only the ${pending.kind} itself is restored; restore racks, shelves or bins below it separately if needed.`
  }
  return pending.kind === 'zone'
    ? 'All racks, shelves and bins in this zone are archived too. Archived locations cannot receive stock.'
    : 'All shelves and bins of this rack are archived too. Archived locations cannot receive stock.'
}

function Totals({ layout }: { layout: WarehouseLayout }) {
  const items = [
    ['Zones', formatInteger(layout.zones.length)],
    [
      'Bins',
      `${formatInteger(layout.totals.active_bins)} active / ${formatInteger(layout.totals.bins)}`,
    ],
    ['Weight capacity', formatNumber(layout.totals.max_weight_kg, 'kg')],
    ['Volume capacity', `${formatInteger(layout.totals.max_volume_cm3 / 1_000_000)} m³`],
  ]
  return (
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <dt className="text-xs font-medium text-slate-500 uppercase">{label}</dt>
          <dd className="mt-1 text-lg font-semibold">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** "Scan" a location code: finds the bin, switches to its zone and highlights it. */
function FindBin({
  onFound,
}: {
  onFound: (locationCode: string, zoneCode: string, warehouseId: number) => void
}) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [found, setFound] = useState<string | null>(null)

  // Bring the bin into view once (not on every later re-render of the page).
  useEffect(() => {
    if (!found) return
    document
      .querySelector(`[data-location-code="${CSS.escape(found)}"]`)
      ?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }, [found])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!code.trim()) return
    setSearching(true)
    setError(null)
    try {
      const bin = await getBinByCode(code)
      onFound(bin.location_code, bin.zone.code, bin.warehouse.id)
      setFound(bin.location_code)
    } catch (err) {
      const status = err instanceof AxiosError ? err.response?.status : undefined
      setError(status === 404 ? 'No bin with this location code' : getErrorMessage(err))
      setFound(null)
    } finally {
      setSearching(false)
    }
  }

  return (
    <form role="search" onSubmit={(e) => void submit(e)} className="flex items-start gap-2">
      <div>
        <input
          aria-label="Location code"
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={error ? 'find-bin-error' : undefined}
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="e.g. WH01-ZA-R07-S03-B05"
          className="w-60 rounded-lg border border-slate-300 bg-white px-3 py-2 font-mono text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/20"
        />
        {error && (
          <p id="find-bin-error" role="alert" className="mt-1 text-xs text-red-600">
            {error}
          </p>
        )}
      </div>
      <Button
        type="submit"
        variant="secondary"
        loading={searching}
        icon={<ScanLine size={14} aria-hidden="true" />}
      >
        Find bin
      </Button>
    </form>
  )
}
