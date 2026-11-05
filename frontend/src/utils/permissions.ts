import type { User } from '../types/auth'
import { hasAnyRole } from './roles'

/** Mirrors the backend rules (app/api/v1/access.py). Admins pass every check. */

/** Create, edit, archive products, categories, suppliers and the warehouse layout. */
export function canEditMasterData(user: User | null): boolean {
  return hasAnyRole(user, ['manager'])
}

/** See costs, margins, suppliers, archived records and the warehouse layout. */
export function isWarehouseUser(user: User | null): boolean {
  return hasAnyRole(user, ['manager', 'staff'])
}
