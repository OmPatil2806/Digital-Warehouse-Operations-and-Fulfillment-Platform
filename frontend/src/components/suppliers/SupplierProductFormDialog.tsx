import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { getErrorMessage } from '../../api/apiClient'
import { addSupplierProduct, catalogKeys, listProducts } from '../../api/catalogApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { Supplier } from '../../types/catalog'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { CheckboxField, NumberField, SelectField, TextField } from '../form/fields'

const offerSchema = z.object({
  product_id: z.string().min(1, 'Choose a product'),
  supplier_sku: z.string().trim().max(60),
  unit_cost: z
    .string()
    .trim()
    .regex(/^\d+(\.\d{1,2})?$/, 'Enter a price like 19.99'),
  lead_time_days: z.string().trim().regex(/^\d*$/, 'Enter a whole number of days'),
  min_order_qty: z
    .string()
    .trim()
    .regex(/^[1-9]\d*$/, 'At least 1'),
  is_preferred: z.boolean(),
})
type OfferValues = z.infer<typeof offerSchema>

interface Props {
  open: boolean
  onClose: () => void
  supplier: Supplier
  /** Products this supplier already offers (hidden from the list). */
  existingProductIds: number[]
}

/** Add a product to a supplier's offer (their SKU, cost, lead time, min. order). */
export function SupplierProductFormDialog({ open, ...props }: Props) {
  return open ? <OfferForm {...props} /> : null
}

function OfferForm({ onClose, supplier, existingProductIds }: Omit<Props, 'open'>) {
  const products = useApiQuery([...catalogKeys.products, 'options'], () =>
    listProducts({ status: 'active', limit: 100, sort: 'sku' }),
  )
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<OfferValues>({
    resolver: zodResolver(offerSchema),
    defaultValues: {
      product_id: '',
      supplier_sku: '',
      unit_cost: '',
      lead_time_days: '',
      min_order_qty: '1',
      is_preferred: false,
    },
  })

  const add = useApiMutation(
    (values: OfferValues) =>
      addSupplierProduct(supplier.id, {
        product_id: Number(values.product_id),
        supplier_sku: values.supplier_sku || null,
        unit_cost: values.unit_cost,
        lead_time_days: values.lead_time_days === '' ? null : Number(values.lead_time_days),
        min_order_qty: Number(values.min_order_qty),
        is_preferred: values.is_preferred,
      }),
    {
      invalidates: [catalogKeys.suppliers, catalogKeys.products],
      successMessage: (offer) => `${offer.product.sku} added to ${supplier.code}`,
      toastOnError: false,
      onSuccess: onClose,
    },
  )

  const options = (products.data?.items ?? [])
    .filter((p) => !existingProductIds.includes(p.id))
    .map((p) => ({ value: p.id, label: `${p.sku} · ${p.name}` }))

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!add.isPending}
      title={`Add product to ${supplier.code}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={add.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="offer-form"
            loading={add.isPending}
            disabled={products.isPending}
          >
            Add product
          </Button>
        </>
      }
    >
      <form
        id="offer-form"
        noValidate
        onSubmit={handleSubmit((v) => add.mutate(v))}
        className="space-y-4"
      >
        {add.errorMessage && (
          <p
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {getErrorMessage(add.error)}
          </p>
        )}
        <SelectField
          label="Product"
          required
          placeholder={products.isPending ? 'Loading…' : 'Choose a product'}
          options={options}
          error={errors.product_id?.message}
          {...register('product_id')}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Supplier's SKU"
            error={errors.supplier_sku?.message}
            {...register('supplier_sku')}
          />
          <NumberField
            label="Unit cost (€)"
            required
            error={errors.unit_cost?.message}
            {...register('unit_cost')}
          />
          <NumberField
            label="Lead time (days)"
            inputMode="numeric"
            hint={`Empty = supplier default (${supplier.lead_time_days} days)`}
            error={errors.lead_time_days?.message}
            {...register('lead_time_days')}
          />
          <NumberField
            label="Minimum order quantity"
            inputMode="numeric"
            error={errors.min_order_qty?.message}
            {...register('min_order_qty')}
          />
        </div>
        <CheckboxField
          label="Preferred supplier for this product"
          hint="Replaces the current preferred supplier, if any"
          {...register('is_preferred')}
        />
      </form>
    </Modal>
  )
}
