import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'

/**
 * Form fields that work directly with React Hook Form:
 *
 *   <TextField label="SKU" error={errors.sku?.message} {...register('sku')} />
 *
 * Each field links its label, hint and error message for screen readers.
 */

interface FieldShellProps {
  id: string
  label: string
  hint?: string
  error?: string
  required?: boolean
  children: ReactNode
}

const inputClass = (hasError: boolean) =>
  'mt-1 block w-full rounded-lg border bg-white px-3 py-2 text-sm shadow-sm outline-none ' +
  'focus:border-blue-600 focus:ring-2 focus:ring-blue-600/20 disabled:bg-slate-50 ' +
  (hasError ? 'border-red-400' : 'border-slate-300')

function FieldShell({ id, label, hint, error, required, children }: FieldShellProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700">
        {label}
        {required && (
          <span className="text-red-600" aria-hidden="true">
            {' '}
            *
          </span>
        )}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

function describedBy(id: string, error?: string, hint?: string) {
  if (error) return `${id}-error`
  return hint ? `${id}-hint` : undefined
}

interface CommonProps {
  label: string
  hint?: string
  error?: string
}

export function TextField({
  label,
  hint,
  error,
  required,
  id,
  ...props
}: CommonProps & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId()
  const fieldId = id ?? autoId
  return (
    <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
      <input
        id={fieldId}
        aria-invalid={error ? 'true' : 'false'}
        aria-describedby={describedBy(fieldId, error, hint)}
        aria-required={required || undefined}
        className={inputClass(Boolean(error))}
        {...props}
      />
    </FieldShell>
  )
}

/** Number input; use with register('field', { valueAsNumber: true }) or keep strings for decimals. */
export function NumberField(props: CommonProps & InputHTMLAttributes<HTMLInputElement>) {
  return <TextField type="text" inputMode="decimal" {...props} />
}

export function SelectField({
  label,
  hint,
  error,
  required,
  id,
  options,
  placeholder,
  ...props
}: CommonProps &
  SelectHTMLAttributes<HTMLSelectElement> & {
    options: { value: string | number; label: string }[]
    placeholder?: string
  }) {
  const autoId = useId()
  const fieldId = id ?? autoId
  return (
    <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
      <select
        id={fieldId}
        aria-invalid={error ? 'true' : 'false'}
        aria-describedby={describedBy(fieldId, error, hint)}
        aria-required={required || undefined}
        className={inputClass(Boolean(error))}
        {...props}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}

export function TextAreaField({
  label,
  hint,
  error,
  required,
  id,
  ...props
}: CommonProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const autoId = useId()
  const fieldId = id ?? autoId
  return (
    <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
      <textarea
        id={fieldId}
        rows={3}
        aria-invalid={error ? 'true' : 'false'}
        aria-describedby={describedBy(fieldId, error, hint)}
        className={inputClass(Boolean(error))}
        {...props}
      />
    </FieldShell>
  )
}

export function CheckboxField({
  label,
  hint,
  id,
  ...props
}: Omit<CommonProps, 'error'> & InputHTMLAttributes<HTMLInputElement>) {
  const autoId = useId()
  const fieldId = id ?? autoId
  return (
    <div className="flex items-start gap-2">
      <input
        id={fieldId}
        type="checkbox"
        aria-describedby={hint ? `${fieldId}-hint` : undefined}
        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-700"
        {...props}
      />
      <div>
        <label htmlFor={fieldId} className="text-sm font-medium text-slate-700">
          {label}
        </label>
        {hint && (
          <p id={`${fieldId}-hint`} className="text-xs text-slate-500">
            {hint}
          </p>
        )}
      </div>
    </div>
  )
}
