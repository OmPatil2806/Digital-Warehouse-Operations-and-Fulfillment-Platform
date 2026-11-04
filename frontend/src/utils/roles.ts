import type { Role, User } from '../types/auth'

/**
 * True if the user has at least one of the given roles.
 * Admins are allowed everywhere (same rule as the backend's require_roles).
 */
export function hasAnyRole(user: User | null, roles: readonly Role[]): boolean {
  if (!user) return false
  if (user.roles.includes('admin')) return true
  return roles.some((role) => user.roles.includes(role))
}
