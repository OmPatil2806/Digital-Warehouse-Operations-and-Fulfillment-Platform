import { AxiosError } from 'axios'

/**
 * Turn a backend error into a message for a specific form field, so that e.g.
 * "A product with this SKU already exists" (409) appears under the SKU input.
 *
 * Returns the field name, or null if the error belongs to the whole form.
 */
const FIELD_RULES: [RegExp, string][] = [
  [/\bSKU\b/i, 'sku'],
  [/\bbarcode\b/i, 'barcode'],
  [/default supplier/i, 'default_supplier_id'],
  [/\bcategory\b/i, 'category_id'],
  [/max_stock/i, 'max_stock'],
  [/supplier with this code/i, 'code'],
  [/already offers this product/i, 'product_id'],
]

export function fieldForError(message: string): string | null {
  for (const [pattern, field] of FIELD_RULES) {
    if (pattern.test(message)) return field
  }
  return null
}

export function isConflictOrValidation(error: unknown): boolean {
  const status = error instanceof AxiosError ? error.response?.status : undefined
  return status === 409 || status === 422
}
