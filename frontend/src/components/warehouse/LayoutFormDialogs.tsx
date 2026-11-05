import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { createWarehouse, createZone, warehouseKeys } from '../../api/warehouseApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { ZONE_TYPES, type Warehouse, type Zone, type ZoneType } from '../../types/warehouse'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { SelectField, TextField } from '../form/fields'

const ZONE_TYPE_LABELS: Record<ZoneType, string> = {
  picking: 'Picking (fast access)',
  bulk: 'Bulk (reserve stock)',
  cold: 'Cold (temperature-controlled)',
  hazardous: 'Hazardous goods',
  returns: 'Returns',
}

function ServerError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p
      role="alert"
      className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      <AlertCircle size={16} aria-hidden="true" />
      {message}
    </p>
  )
}

// ------------------------------------------------------------------------ warehouse
const warehouseSchema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[Ww][Hh]\d{2,4}$/, 'Use WH followed by 2–4 digits, e.g. WH02'),
  name: z.string().trim().min(1, 'Name is required').max(120),
  address: z.string().trim().max(255),
})

export function WarehouseFormDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (warehouse: Warehouse) => void
}) {
  return open ? <WarehouseForm onClose={onClose} onCreated={onCreated} /> : null
}

function WarehouseForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (w: Warehouse) => void
}) {
  const { register, handleSubmit, formState } = useForm<z.infer<typeof warehouseSchema>>({
    resolver: zodResolver(warehouseSchema),
    defaultValues: { code: '', name: '', address: '' },
  })
  const create = useApiMutation(
    (v: z.infer<typeof warehouseSchema>) =>
      createWarehouse({ code: v.code, name: v.name, address: v.address || null }),
    {
      invalidates: [warehouseKeys.all],
      successMessage: (w) => `Warehouse ${w.code} created`,
      toastOnError: false,
      onSuccess: (w) => {
        onCreated(w)
        onClose()
      },
    },
  )
  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!create.isPending}
      title="New warehouse"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="warehouse-form" loading={create.isPending}>
            Create warehouse
          </Button>
        </>
      }
    >
      <form
        id="warehouse-form"
        noValidate
        onSubmit={handleSubmit((v) => create.mutate(v))}
        className="space-y-4"
      >
        <ServerError message={create.errorMessage} />
        <TextField
          label="Code"
          required
          hint="e.g. WH02 — cannot be changed later"
          error={formState.errors.code?.message}
          {...register('code')}
        />
        <TextField
          label="Name"
          required
          error={formState.errors.name?.message}
          {...register('name')}
        />
        <TextField
          label="Address"
          error={formState.errors.address?.message}
          {...register('address')}
        />
      </form>
    </Modal>
  )
}

// ----------------------------------------------------------------------------- zone
const zoneSchema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[Zz][A-Za-z]{1,2}$/, 'Use Z followed by 1–2 letters, e.g. ZD'),
  name: z.string().trim().min(1, 'Name is required').max(80),
  zone_type: z.enum(ZONE_TYPES, 'Choose a zone type'),
})

export function ZoneFormDialog({
  warehouse,
  onClose,
  onCreated,
}: {
  warehouse: Warehouse | null
  onClose: () => void
  onCreated: (zone: Zone) => void
}) {
  return warehouse ? (
    <ZoneForm warehouse={warehouse} onClose={onClose} onCreated={onCreated} />
  ) : null
}

function ZoneForm({
  warehouse,
  onClose,
  onCreated,
}: {
  warehouse: Warehouse
  onClose: () => void
  onCreated: (zone: Zone) => void
}) {
  const { register, handleSubmit, formState } = useForm<z.infer<typeof zoneSchema>>({
    resolver: zodResolver(zoneSchema),
    defaultValues: { code: '', name: '', zone_type: 'picking' },
  })
  const create = useApiMutation((v: z.infer<typeof zoneSchema>) => createZone(warehouse.id, v), {
    invalidates: [[...warehouseKeys.all, warehouse.id]],
    successMessage: (z) => `Zone ${z.code} created`,
    toastOnError: false,
    onSuccess: (z) => {
      onCreated(z)
      onClose()
    },
  })
  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!create.isPending}
      title={`New zone in ${warehouse.code}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="zone-form" loading={create.isPending}>
            Create zone
          </Button>
        </>
      }
    >
      <form
        id="zone-form"
        noValidate
        onSubmit={handleSubmit((v) => create.mutate(v))}
        className="space-y-4"
      >
        <ServerError message={create.errorMessage} />
        <TextField
          label="Code"
          required
          hint="e.g. ZD — cannot be changed later"
          error={formState.errors.code?.message}
          {...register('code')}
        />
        <TextField
          label="Name"
          required
          error={formState.errors.name?.message}
          {...register('name')}
        />
        <SelectField
          label="Type"
          required
          options={ZONE_TYPES.map((type) => ({ value: type, label: ZONE_TYPE_LABELS[type] }))}
          error={formState.errors.zone_type?.message}
          {...register('zone_type')}
        />
      </form>
    </Modal>
  )
}
