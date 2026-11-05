import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle, AlertTriangle } from 'lucide-react'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'

import { getErrorMessage } from '../../api/apiClient'
import {
  catalogKeys,
  createProduct,
  listCategories,
  listSuppliers,
  updateProduct,
} from '../../api/catalogApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type { Product, ProductInput } from '../../types/catalog'
import { fieldForError } from '../../utils/apiErrors'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { NumberField, SelectField, TextAreaField, TextField } from '../form/fields'

const decimal = (places: number, label: string, { positive = false } = {}) =>
  z
    .string()
    .trim()
    .min(1, `${label} is required`)
    .regex(
      new RegExp(`^\\d+(\\.\\d{1,${places}})?$`),
      `Enter a number with at most ${places} decimal place${places > 1 ? 's' : ''}`,
    )
    .refine((value) => !positive || Number(value) > 0, `${label} must be greater than 0`)

const optionalInteger = z.string().trim().regex(/^\d*$/, 'Enter a whole number')

const productSchema = z
  .object({
    sku: z
      .string()
      .trim()
      .min(2, 'SKU must have at least 2 characters')
      .max(40)
      .regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/, 'Use letters, digits, "-", "_" or "."'),
    name: z.string().trim().min(1, 'Name is required').max(160),
    category_id: z.string().min(1, 'Choose a category'),
    brand: z.string().trim().max(80),
    description: z.string().trim().max(5000),
    unit_price: decimal(2, 'Price'),
    unit_cost: decimal(2, 'Cost'),
    weight_kg: decimal(3, 'Weight', { positive: true }),
    length_cm: decimal(1, 'Length', { positive: true }),
    width_cm: decimal(1, 'Width', { positive: true }),
    height_cm: decimal(1, 'Height', { positive: true }),
    barcode: z
      .string()
      .trim()
      .regex(/^(|\d{8}|\d{12,14})$/, 'Barcode must have 8, 12, 13 or 14 digits'),
    min_stock: optionalInteger,
    max_stock: optionalInteger,
    default_supplier_id: z.string(),
  })
  .refine((v) => !v.max_stock || Number(v.max_stock) >= Number(v.min_stock || 0), {
    path: ['max_stock'],
    message: 'Max stock must be at least the min stock',
  })

type ProductFormValues = z.infer<typeof productSchema>

const EMPTY: ProductFormValues = {
  sku: '',
  name: '',
  category_id: '',
  brand: '',
  description: '',
  unit_price: '',
  unit_cost: '',
  weight_kg: '',
  length_cm: '',
  width_cm: '',
  height_cm: '',
  barcode: '',
  min_stock: '0',
  max_stock: '',
  default_supplier_id: '',
}

function toFormValues(product: Product): ProductFormValues {
  return {
    sku: product.sku,
    name: product.name,
    category_id: String(product.category.id),
    brand: product.brand ?? '',
    description: product.description ?? '',
    unit_price: product.unit_price,
    unit_cost: product.unit_cost ?? '',
    weight_kg: product.weight_kg,
    length_cm: product.length_cm,
    width_cm: product.width_cm,
    height_cm: product.height_cm,
    barcode: product.barcode ?? '',
    min_stock: String(product.min_stock ?? 0),
    max_stock: product.max_stock == null ? '' : String(product.max_stock),
    default_supplier_id: product.default_supplier ? String(product.default_supplier.id) : '',
  }
}

function toInput(values: ProductFormValues): ProductInput {
  const orNull = (value: string) => (value === '' ? null : value)
  return {
    sku: values.sku,
    name: values.name,
    category_id: Number(values.category_id),
    brand: orNull(values.brand),
    description: orNull(values.description),
    unit_price: values.unit_price,
    unit_cost: values.unit_cost,
    weight_kg: values.weight_kg,
    length_cm: values.length_cm,
    width_cm: values.width_cm,
    height_cm: values.height_cm,
    barcode: orNull(values.barcode),
    min_stock: Number(values.min_stock || 0),
    max_stock: values.max_stock === '' ? null : Number(values.max_stock),
    default_supplier_id:
      values.default_supplier_id === '' ? null : Number(values.default_supplier_id),
  }
}

interface ProductFormDialogProps {
  open: boolean
  onClose: () => void
  /** Edit this product; create a new one when omitted. */
  product?: Product
  onSaved?: (product: Product) => void
}

export function ProductFormDialog({ open, onClose, product, onSaved }: ProductFormDialogProps) {
  // Re-mount the form for each product so default values are always fresh.
  return open ? (
    <ProductForm key={product?.id ?? 'new'} onClose={onClose} product={product} onSaved={onSaved} />
  ) : null
}

function ProductForm({ onClose, product, onSaved }: Omit<ProductFormDialogProps, 'open'>) {
  const categories = useApiQuery(catalogKeys.categories, listCategories)
  const suppliers = useApiQuery([...catalogKeys.suppliers, 'options'], () =>
    listSuppliers({ status: 'active', limit: 100 }),
  )

  // The dropdowns must have their options BEFORE the form sets its values; otherwise a
  // <select> cannot show (or submit) the product's current category in edit mode.
  if (categories.isPending || suppliers.isPending || categories.errorMessage) {
    return (
      <Modal open onClose={onClose} title={product ? `Edit ${product.sku}` : 'New product'}>
        {categories.errorMessage ? (
          <p role="alert" className="text-sm text-red-700">
            {categories.errorMessage}
          </p>
        ) : (
          <p role="status" className="text-sm text-slate-500">
            Loading…
          </p>
        )}
      </Modal>
    )
  }

  const categoryOptions = (categories.data?.items ?? [])
    .filter((c) => c.is_active || c.id === product?.category.id)
    .map((c) => ({ value: c.id, label: c.name }))
  const supplierOptions = (suppliers.data?.items ?? []).map((s) => ({
    value: s.id,
    label: `${s.code} · ${s.name}`,
  }))
  return (
    <ProductFormBody
      onClose={onClose}
      product={product}
      onSaved={onSaved}
      categoryOptions={categoryOptions}
      supplierOptions={supplierOptions}
    />
  )
}

interface Option {
  value: number
  label: string
}

function ProductFormBody({
  onClose,
  product,
  onSaved,
  categoryOptions,
  supplierOptions,
}: Omit<ProductFormDialogProps, 'open'> & {
  categoryOptions: Option[]
  supplierOptions: Option[]
}) {
  const editing = product !== undefined
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors },
  } = useForm<ProductFormValues>({
    resolver: zodResolver(productSchema),
    defaultValues: product ? toFormValues(product) : EMPTY,
  })
  const [price, cost] = useWatch({ control, name: ['unit_price', 'unit_cost'] })
  const sellsBelowCost = price !== '' && cost !== '' && Number(price) < Number(cost)

  const save = useApiMutation(
    (values: ProductFormValues) =>
      editing ? updateProduct(product.id, toInput(values)) : createProduct(toInput(values)),
    {
      invalidates: [catalogKeys.products],
      successMessage: (saved) => `Product ${saved.sku} ${editing ? 'updated' : 'created'}`,
      toastOnError: false,
      onSuccess: (saved) => {
        onSaved?.(saved)
        onClose()
      },
    },
  )

  const onSubmit = (values: ProductFormValues) =>
    save.mutate(values, {
      onError: (error) => {
        const field = fieldForError(getErrorMessage(error))
        if (field) setError(field as keyof ProductFormValues, { message: getErrorMessage(error) })
      },
    })

  const serverError =
    save.errorMessage && !fieldForError(save.errorMessage) ? save.errorMessage : null

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!save.isPending}
      size="lg"
      title={editing ? `Edit ${product.sku}` : 'New product'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="product-form" loading={save.isPending}>
            {editing ? 'Save changes' : 'Create product'}
          </Button>
        </>
      }
    >
      <form id="product-form" noValidate onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        {serverError && (
          <p
            role="alert"
            className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            <AlertCircle size={16} aria-hidden="true" />
            {serverError}
          </p>
        )}

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="sr-only">General</legend>
          <TextField
            label="SKU"
            required
            hint="Stored in upper case"
            error={errors.sku?.message}
            {...register('sku')}
          />
          <TextField label="Name" required error={errors.name?.message} {...register('name')} />
          <SelectField
            label="Category"
            required
            placeholder="Select a category…"
            options={categoryOptions}
            error={errors.category_id?.message}
            {...register('category_id')}
          />
          <TextField label="Brand" error={errors.brand?.message} {...register('brand')} />
          <div className="sm:col-span-2">
            <TextAreaField
              label="Description"
              error={errors.description?.message}
              {...register('description')}
            />
          </div>
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-semibold text-slate-800">Price</legend>
          <NumberField
            label="Selling price (€)"
            required
            error={errors.unit_price?.message}
            {...register('unit_price')}
          />
          <NumberField
            label="Purchase cost (€)"
            required
            error={errors.unit_cost?.message}
            {...register('unit_cost')}
          />
          {sellsBelowCost && (
            <p
              role="status"
              className="flex items-center gap-2 text-sm text-amber-700 sm:col-span-2"
            >
              <AlertTriangle size={16} aria-hidden="true" />
              The selling price is below the purchase cost — this product will be sold at a loss.
            </p>
          )}
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-4">
          <legend className="mb-2 text-sm font-semibold text-slate-800">Size and weight</legend>
          <NumberField
            label="Weight (kg)"
            required
            error={errors.weight_kg?.message}
            {...register('weight_kg')}
          />
          <NumberField
            label="Length (cm)"
            required
            error={errors.length_cm?.message}
            {...register('length_cm')}
          />
          <NumberField
            label="Width (cm)"
            required
            error={errors.width_cm?.message}
            {...register('width_cm')}
          />
          <NumberField
            label="Height (cm)"
            required
            error={errors.height_cm?.message}
            {...register('height_cm')}
          />
        </fieldset>

        <fieldset className="grid gap-4 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-semibold text-slate-800">Stock and supply</legend>
          <NumberField
            label="Min stock"
            inputMode="numeric"
            error={errors.min_stock?.message}
            {...register('min_stock')}
          />
          <NumberField
            label="Max stock"
            inputMode="numeric"
            hint="Leave empty for no limit"
            error={errors.max_stock?.message}
            {...register('max_stock')}
          />
          <TextField
            label="Barcode (EAN/UPC)"
            inputMode="numeric"
            error={errors.barcode?.message}
            {...register('barcode')}
          />
          <SelectField
            label="Default supplier"
            placeholder="None"
            options={supplierOptions}
            error={errors.default_supplier_id?.message}
            {...register('default_supplier_id')}
          />
        </fieldset>
      </form>
    </Modal>
  )
}
