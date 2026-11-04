import { zodResolver } from '@hookform/resolvers/zod'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useForm } from 'react-hook-form'
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { CheckboxField, NumberField, SelectField, TextAreaField, TextField } from './fields'

const schema = z.object({
  sku: z.string().min(2, 'SKU is too short'),
  price: z.string().regex(/^\d+(\.\d{1,2})?$/, 'Enter a price like 19.99'),
  category: z.string().min(1, 'Choose a category'),
  description: z.string(),
  active: z.boolean(),
})
type Values = z.infer<typeof schema>

function ProductForm({ onSubmit }: { onSubmit: (values: Values) => void }) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { sku: '', price: '', category: '', description: '', active: true },
  })
  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate>
      <TextField
        label="SKU"
        required
        hint="Letters and digits"
        error={errors.sku?.message}
        {...register('sku')}
      />
      <NumberField label="Price" error={errors.price?.message} {...register('price')} />
      <SelectField
        label="Category"
        placeholder="Choose…"
        options={[
          { value: '1', label: 'Electronics' },
          { value: '2', label: 'Tools' },
        ]}
        error={errors.category?.message}
        {...register('category')}
      />
      <TextAreaField label="Description" {...register('description')} />
      <CheckboxField label="Active" hint="Visible to customers" {...register('active')} />
      <button type="submit">Save</button>
    </form>
  )
}

describe('form fields', () => {
  it('link labels, hints and required markers', () => {
    render(<ProductForm onSubmit={vi.fn()} />)

    const sku = screen.getByRole('textbox', { name: /SKU/ })
    expect(sku).toHaveAttribute('aria-required', 'true')
    expect(sku).toHaveAccessibleDescription('Letters and digits')
    expect(screen.getByRole('textbox', { name: 'Price' })).toHaveAttribute('inputmode', 'decimal')
    expect(screen.getByRole('checkbox', { name: 'Active' })).toHaveAccessibleDescription(
      'Visible to customers',
    )
  })

  it('show validation errors from React Hook Form + Zod', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<ProductForm onSubmit={onSubmit} />)

    await user.type(screen.getByRole('textbox', { name: 'Price' }), '1.999')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    const sku = screen.getByRole('textbox', { name: /SKU/ })
    expect(sku).toHaveAttribute('aria-invalid', 'true')
    expect(sku).toHaveAccessibleDescription('SKU is too short') // error replaces the hint
    expect(screen.getByText('Enter a price like 19.99')).toBeInTheDocument()
    expect(screen.getByText('Choose a category')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('submit the entered values', async () => {
    const onSubmit = vi.fn()
    const user = userEvent.setup()
    render(<ProductForm onSubmit={onSubmit} />)

    await user.type(screen.getByRole('textbox', { name: /SKU/ }), 'LAP-001')
    await user.type(screen.getByRole('textbox', { name: 'Price' }), '899.99')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Category' }), 'Tools')
    await user.type(screen.getByRole('textbox', { name: 'Description' }), 'Light')
    await user.click(screen.getByRole('checkbox', { name: 'Active' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(onSubmit.mock.calls[0][0]).toEqual({
      sku: 'LAP-001',
      price: '899.99',
      category: '2',
      description: 'Light',
      active: false,
    })
  })
})
