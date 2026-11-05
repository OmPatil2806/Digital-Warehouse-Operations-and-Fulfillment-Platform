import type {
  Bin,
  LayoutRack,
  LayoutShelf,
  LayoutZone,
  WarehouseLayout,
} from '../../types/warehouse'

/**
 * How full a bin is (0–1). Stock arrives in Phase 4; until then every bin is empty.
 * The colour scale below is already in place so the page will not change shape later.
 */
export function binOccupancy(bin: Bin): number {
  void bin
  return 0
}

export const OCCUPANCY_LEVELS = [
  { label: 'Empty', max: 0, className: 'bg-white border-slate-300' },
  { label: 'Up to 50 %', max: 0.5, className: 'bg-emerald-50 border-emerald-300' },
  { label: 'Up to 85 %', max: 0.85, className: 'bg-amber-50 border-amber-300' },
  { label: 'Almost full', max: 1, className: 'bg-red-50 border-red-300' },
] as const

export interface BinSelection {
  bin: Bin
  shelf: LayoutShelf
  rack: LayoutRack
  zone: LayoutZone
}

/** Find where a bin sits in the layout tree. */
export function locateBin(layout: WarehouseLayout, locationCode: string): BinSelection | null {
  for (const zone of layout.zones) {
    for (const rack of zone.racks) {
      for (const shelf of rack.shelves) {
        const bin = shelf.bins.find((b) => b.location_code === locationCode)
        if (bin) return { bin, shelf, rack, zone }
      }
    }
  }
  return null
}
