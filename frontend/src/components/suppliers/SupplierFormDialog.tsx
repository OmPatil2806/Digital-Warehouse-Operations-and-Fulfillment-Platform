import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { getErrorMessage } from '../../api/apiClient'
import { catalogKeys, createSupplier, updateSupplier } from '../../api/catalogApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import type { Supplier, SupplierInput } from '../../types/catalog'
import { fieldForError } from '../../utils/apiErrors'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { NumberField, TextField } from '../form/fields'

const supplierSchema = z.object({
  code: z
    .string()
    .trim()
    .min(2, 'Code must have at least 2 characters')
    .max(20)
    .regex(/^[A-Za-z0-9][A-Za-z0-9-]*$/, 'Use letters, digits and "-" (e.g. SUP-011)'),
  name: z.string().trim().min(1, 'Name is required').max(120),
  contact_name: z.string().trim().max(120),
  email: z.union([z.literal(''), z.email('Enter a valid email address')]),
  phone: z.string().trim().max(40),
  address: z.string().trim().max(255),
  country: z.string().trim().max(80),
  lead_time_days: z
    .string()
    .trim()
    .regex(/^\d+$/, 'Enter a whole number of days')
    .refine((v) => Number(v) <= 365, 'At most 365 days'),
  reliability_percent: z
    .string()
    .trim()
    .regex(/^\d{1,3}$/, 'Enter a whole percentage')
    .refine((v) => Number(v) <= 100, 'At most 100 %'),
})

type SupplierFormValues = z.infer<typeof supplierSchema>

function toFormValues(supplier?: Supplier): SupplierFormValues {
  return {
    code: supplier?.code ?? '',
    name: supplier?.name ?? '',
    contact_name: supplier?.contact_name ?? '',
    email: supplier?.email ?? '',
    phone: supplier?.phone ?? '',
    address: supplier?.address ?? '',
    country: supplier?.country ?? '',
    lead_time_days: String(supplier?.lead_time_days ?? 7),
    reliability_percent: String(Math.round(Number(supplier?.reliability_score ?? '0.95') * 100)),
  }
}

function toInput(values: SupplierFormValues): SupplierInput {
  const orNull = (value: string) => (value.trim() === '' ? null : value.trim())
  return {
    code: values.code,
    name: values.name,
    contact_name: orNull(values.contact_name),
    email: orNull(values.email),
    phone: orNull(values.phone),
    address: orNull(values.address),
    country: orNull(values.country),
    lead_time_days: Number(values.lead_time_days),
    reliability_score: (Number(values.reliability_percent) / 100).toFixed(2),
  }
}

interface SupplierFormDialogProps {
  open: boolean
  onClose: () => void
  supplier?: Supplier
  onSaved?: (supplier: Supplier) => void
}

export function SupplierFormDialog({ open, ...props }: SupplierFormDialogProps) {
  return open ? <SupplierForm key={props.supplier?.id ?? 'new'} {...props} /> : null
}

function SupplierForm({ onClose, supplier, onSaved }: Omit<SupplierFormDialogProps, 'open'>) {
  const editing = supplier !== undefined
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<SupplierFormValues>({
    resolver: zodResolver(supplierSchema),
    defaultValues: toFormValues(supplier),
  })

  const save = useApiMutation(
    (values: SupplierFormValues) =>
      editing ? updateSupplier(supplier.id, toInput(values)) : createSupplier(toInput(values)),
    {
      invalidates: [catalogKeys.suppliers],
      successMessage: (saved) => `Supplier ${saved.code} ${editing ? 'updated' : 'created'}`,
      toastOnError: false,
      onSuccess: (saved) => {
        onSaved?.(saved)
        onClose()
      },
    },
  )

  const onSubmit = (values: SupplierFormValues) =>
    save.mutate(values, {
      onError: (error) => {
        if (fieldForError(getErrorMessage(error)) === 'code') {
          setError('code', { message: getErrorMessage(error) })
        }
      },
    })

  const serverError =
    save.errorMessage && fieldForError(save.errorMessage) !== 'code' ? save.errorMessage : null

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!save.isPending}
      title={editing ? `Edit ${supplier.code}` : 'New supplier'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="supplier-form" loading={save.isPending}>
            {editing ? 'Save changes' : 'Create supplier'}
          </Button>
        </>
      }
    >
      <form id="supplier-form" noValidate onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {serverError && (
          <p
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {serverError}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Code"
            required
            hint="e.g. SUP-011"
            error={errors.code?.message}
            {...register('code')}
          />
          <TextField label="Name" required error={errors.name?.message} {...register('name')} />
          <TextField
            label="Contact person"
            error={errors.contact_name?.message}
            {...register('contact_name')}
          />
          <TextField
            label="Email"
            type="email"
            error={errors.email?.message}
            {...register('email')}
          />
          <TextField label="Phone" error={errors.phone?.message} {...register('phone')} />
          <TextField label="Country" error={errors.country?.message} {...register('country')} />
          <div className="sm:col-span-2">
            <TextField label="Address" error={errors.address?.message} {...register('address')} />
          </div>
          <NumberField
            label="Lead time (days)"
            required
            inputMode="numeric"
            hint="Typical days from order to delivery"
            error={errors.lead_time_days?.message}
            {...register('lead_time_days')}
          />
          <NumberField
            label="Reliability (%)"
            required
            inputMode="numeric"
            hint="Share of on-time, complete deliveries"
            error={errors.reliability_percent?.message}
            {...register('reliability_percent')}
          />
        </div>
      </form>
    </Modal>
  )
}
