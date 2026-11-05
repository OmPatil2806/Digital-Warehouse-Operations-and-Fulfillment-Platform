import { Archive, ArchiveRestore, Footprints } from 'lucide-react'

import type { Bin, LayoutRack } from '../../types/warehouse'
import { Button } from '../common/Button'
import { binOccupancy, OCCUPANCY_LEVELS } from './layoutUtils'

function occupancyClass(bin: Bin): string {
  if (!bin.is_active) return 'border-dashed border-slate-300 bg-slate-100 text-slate-400'
  const fill = binOccupancy(bin)
  return (OCCUPANCY_LEVELS.find((level) => fill <= level.max) ?? OCCUPANCY_LEVELS[3]).className
}

interface LayoutGridProps {
  racks: LayoutRack[]
  /** Location code of a bin to highlight (e.g. after "Find bin"). */
  highlighted?: string | null
  onSelectBin: (bin: Bin) => void
  /** When given, racks get an Archive / Restore button. */
  onToggleRack?: (rack: LayoutRack) => void
}

/**
 * Racks of one zone, in the order the API returns them (closest to packing first).
 * Each rack lists its shelves from the top level down to the floor, like standing in front of it.
 */
export function LayoutGrid({ racks, highlighted, onSelectBin, onToggleRack }: LayoutGridProps) {
  if (racks.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        This zone has no racks yet.
      </p>
    )
  }

  return (
    <ol aria-label="Racks" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {racks.map((rack) => (
        <li
          key={rack.id}
          aria-label={`Rack ${rack.code}`}
          className={`rounded-xl border bg-white p-4 shadow-sm ${rack.is_active ? 'border-slate-200' : 'border-dashed border-slate-300 opacity-70'}`}
        >
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h3 className="font-semibold">
                {rack.code}
                {!rack.is_active && (
                  <span className="ml-2 text-xs font-normal text-slate-500">archived</span>
                )}
              </h3>
              <p className="flex items-center gap-1 text-xs text-slate-500">
                <Footprints size={12} aria-hidden="true" />
                {Number(rack.distance_to_packing_m).toLocaleString('en-IE')} m to packing
              </p>
            </div>
            {onToggleRack && (
              <Button
                variant="ghost"
                size="sm"
                aria-label={`${rack.is_active ? 'Archive' : 'Restore'} rack ${rack.code}`}
                icon={
                  rack.is_active ? (
                    <Archive size={14} aria-hidden="true" />
                  ) : (
                    <ArchiveRestore size={14} aria-hidden="true" />
                  )
                }
                onClick={() => onToggleRack(rack)}
              />
            )}
          </div>

          <div className="space-y-1.5">
            {[...rack.shelves]
              .sort((a, b) => b.level - a.level)
              .map((shelf) => (
                <div key={shelf.id} className="flex items-center gap-2">
                  <span
                    className="w-8 shrink-0 text-right text-[11px] font-medium text-slate-500"
                    title={`Shelf ${shelf.code}, level ${shelf.level}`}
                  >
                    {shelf.code}
                  </span>
                  <ul aria-label={`Shelf ${shelf.code}`} className="flex flex-1 flex-wrap gap-1">
                    {shelf.bins.map((bin) => (
                      <li key={bin.id}>
                        <button
                          type="button"
                          data-location-code={bin.location_code}
                          aria-label={`Bin ${bin.location_code}${bin.is_active ? '' : ' (archived)'}`}
                          aria-current={highlighted === bin.location_code ? 'location' : undefined}
                          onClick={() => onSelectBin(bin)}
                          className={`h-8 min-w-9 rounded border px-1 text-[10px] font-medium transition hover:ring-2 hover:ring-blue-300 ${occupancyClass(bin)} ${
                            highlighted === bin.location_code
                              ? 'ring-2 ring-blue-600 ring-offset-1'
                              : ''
                          }`}
                        >
                          {bin.code}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            <p className="pl-10 text-[10px] tracking-wide text-slate-400 uppercase">floor</p>
          </div>
        </li>
      ))}
    </ol>
  )
}

export function OccupancyLegend() {
  return (
    <ul aria-label="Legend" className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
      {OCCUPANCY_LEVELS.map((level) => (
        <li key={level.label} className="flex items-center gap-1.5">
          <span
            className={`inline-block h-3 w-4 rounded border ${level.className}`}
            aria-hidden="true"
          />
          {level.label}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span
          className="inline-block h-3 w-4 rounded border border-dashed border-slate-300 bg-slate-100"
          aria-hidden="true"
        />
        Archived
      </li>
      <li className="text-slate-400">· fill levels appear once stock is stored (Phase 4)</li>
    </ul>
  )
}
