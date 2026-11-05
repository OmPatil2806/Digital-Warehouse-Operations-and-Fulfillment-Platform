import { z } from 'zod'

import { ROLES } from '../../types/auth'

/** Mirrors the backend password policy (app/schemas/user.py). */
export const passwordSchema = z
  .string()
  .min(8, 'At least 8 characters')
  .refine((v) => new TextEncoder().encode(v).length <= 72, 'At most 72 bytes')
  .refine((v) => /\p{L}/u.test(v), 'Must contain a letter')
  .refine((v) => /\d/.test(v), 'Must contain a digit')

export const rolesSchema = z.array(z.enum(ROLES)).min(1, 'Choose at least one role')

export const ROLE_DESCRIPTIONS = {
  admin: 'Users, roles, settings and everything else',
  manager: 'Catalog, warehouse layout, KPIs and approvals',
  staff: 'Receiving, picking and packing (read-only master data)',
  customer: 'Places and tracks orders',
} as const
