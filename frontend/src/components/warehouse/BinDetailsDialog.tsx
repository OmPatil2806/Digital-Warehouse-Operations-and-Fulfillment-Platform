import { StatusBadge } from '../common/Badge'
import { Modal } from '../common/Modal'
import { DetailItem } from '../common/PageHeader'
import { formatInteger, formatNumber } from '../../utils/format'
import { binOccupancy, type BinSelection } from './layoutUtils'

export function BinDetailsDialog({
  selection,
  warehouseCode,
  onClose,
}: {
  selection: BinSelection | null
  warehouseCode: string
  onClose: () => void
}) {
  if (!selection) return null
  const { bin, shelf, rack, zone } = selection
  const fill = binOccupancy(bin)

  return (
    <Modal open onClose={onClose} title={bin.location_code} description="Storage bin" size="sm">
      <dl className="grid grid-cols-2 gap-4">
        <DetailItem label="Warehouse">{warehouseCode}</DetailItem>
        <DetailItem label="Zone">
          {zone.code} · {zone.name}
        </DetailItem>
        <DetailItem label="Rack">
          {rack.code} ({formatNumber(rack.distance_to_packing_m, 'm')} to packing)
        </DetailItem>
        <DetailItem label="Shelf">
          {shelf.code} (level {shelf.level})
        </DetailItem>
        <DetailItem label="Max weight">{formatNumber(bin.max_weight_kg, 'kg')}</DetailItem>
        <DetailItem label="Max volume">{formatInteger(bin.max_volume_cm3)} cm³</DetailItem>
        <DetailItem label="Status">
          <StatusBadge active={bin.is_active} />
        </DetailItem>
        <DetailItem label="Occupancy">{Math.round(fill * 100)} %</DetailItem>
      </dl>
      <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
        Stock in this bin and its movement history arrive in Phase 4 (inventory operations).
      </p>
    </Modal>
  )
}
