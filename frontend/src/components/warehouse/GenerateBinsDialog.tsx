import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle, Sparkles } from 'lucide-react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'

import { generateLayout, warehouseKeys } from '../../api/warehouseApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import type { LayoutZone } from '../../types/warehouse'
import { formatInteger } from '../../utils/format'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { NumberField } from '../form/fields'

/** Same limit as the backend (GenerateLayoutRequest). */
const MAX_GENERATED_BINS = 5000

const wholeNumber = (label: string, min: number, max: number) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, `${label}: enter a whole number`)
    .refine((v) => Number(v) >= min && Number(v) <= max, `${label}: between ${min} and ${max}`)

const decimal = (label: string, places: number, { positive }: { positive: boolean }) =>
  z
    .string()
    .trim()
    .regex(new RegExp(`^\\d+(\\.\\d{1,${places}})?$`), `${label}: up to ${places} decimal places`)
    .refine((v) => !positive || Number(v) > 0, `${label} must be greater than 0`)

const schema = z
  .object({
    racks: wholeNumber('Racks', 1, 99),
    shelves_per_rack: wholeNumber('Shelves per rack', 1, 20),
    bins_per_shelf: wholeNumber('Bins per shelf', 1, 99),
    max_weight_kg: decimal('Max weight', 3, { positive: true }),
    max_volume_cm3: wholeNumber('Max volume', 1, 1_000_000_000),
    first_rack_distance_m: decimal('First rack distance', 1, { positive: false }),
    distance_step_m: decimal('Distance step', 1, { positive: false }),
  })
  .refine(
    (v) =>
      Number(v.racks) * Number(v.shelves_per_rack) * Number(v.bins_per_shelf) <= MAX_GENERATED_BINS,
    { path: ['bins_per_shelf'], message: `At most ${MAX_GENERATED_BINS} bins per run` },
  )
type Values = z.infer<typeof schema>

interface Props {
  zone: LayoutZone | null
  warehouseId: number
  onClose: () => void
}

export function GenerateBinsDialog({ zone, ...props }: Props) {
  return zone ? <GenerateForm key={zone.id} zone={zone} {...props} /> : null
}

function GenerateForm({ zone, warehouseId, onClose }: Props & { zone: LayoutZone }) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      racks: '4',
      shelves_per_rack: '4',
      bins_per_shelf: '6',
      max_weight_kg: '30',
      max_volume_cm3: '120000',
      first_rack_distance_m: '5',
      distance_step_m: '2',
    },
  })
  const [racks, shelves, bins] = useWatch({
    control,
    name: ['racks', 'shelves_per_rack', 'bins_per_shelf'],
  })
  const total = (Number(racks) || 0) * (Number(shelves) || 0) * (Number(bins) || 0)

  const generate = useApiMutation(
    (values: Values) =>
      generateLayout(zone.id, {
        racks: Number(values.racks),
        shelves_per_rack: Number(values.shelves_per_rack),
        bins_per_shelf: Number(values.bins_per_shelf),
        max_weight_kg: values.max_weight_kg,
        max_volume_cm3: Number(values.max_volume_cm3),
        first_rack_distance_m: values.first_rack_distance_m,
        distance_step_m: values.distance_step_m,
      }),
    {
      invalidates: [[...warehouseKeys.all, warehouseId]],
      successMessage: (r) =>
        `${formatInteger(r.bins_created)} bins created (${r.first_location_code} … ${r.last_location_code})`,
      toastOnError: false,
      onSuccess: onClose,
    },
  )

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!generate.isPending}
      title={`Generate bins in zone ${zone.code}`}
      description="New racks are numbered after the highest existing rack in this zone. Nothing is created if any location already exists."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={generate.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="generate-form"
            loading={generate.isPending}
            icon={<Sparkles size={14} aria-hidden="true" />}
          >
            Generate {formatInteger(total)} bins
          </Button>
        </>
      }
    >
      <form
        id="generate-form"
        noValidate
        onSubmit={handleSubmit((v) => generate.mutate(v))}
        className="space-y-4"
      >
        {generate.errorMessage && (
          <p
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {generate.errorMessage}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <NumberField
            label="Racks"
            inputMode="numeric"
            error={errors.racks?.message}
            {...register('racks')}
          />
          <NumberField
            label="Shelves per rack"
            inputMode="numeric"
            error={errors.shelves_per_rack?.message}
            {...register('shelves_per_rack')}
          />
          <NumberField
            label="Bins per shelf"
            inputMode="numeric"
            error={errors.bins_per_shelf?.message}
            {...register('bins_per_shelf')}
          />
          <NumberField
            label="Max weight per bin (kg)"
            error={errors.max_weight_kg?.message}
            {...register('max_weight_kg')}
          />
          <NumberField
            label="Max volume per bin (cm³)"
            inputMode="numeric"
            error={errors.max_volume_cm3?.message}
            {...register('max_volume_cm3')}
          />
          <div />
          <NumberField
            label="First rack: distance to packing (m)"
            error={errors.first_rack_distance_m?.message}
            {...register('first_rack_distance_m')}
          />
          <NumberField
            label="Each further rack: + metres"
            error={errors.distance_step_m?.message}
            {...register('distance_step_m')}
          />
        </div>
        <p
          role="status"
          className={`rounded-lg px-3 py-2 text-sm ${total > MAX_GENERATED_BINS ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-800'}`}
        >
          Will create <strong>{formatInteger(Number(racks) || 0)}</strong> racks ×{' '}
          <strong>{formatInteger(Number(shelves) || 0)}</strong> shelves ×{' '}
          <strong>{formatInteger(Number(bins) || 0)}</strong> bins ={' '}
          <strong>{formatInteger(total)} bins</strong>
          {total > MAX_GENERATED_BINS &&
            ` — more than the limit of ${formatInteger(MAX_GENERATED_BINS)}`}
        </p>
      </form>
    </Modal>
  )
}
