import type { ReactNode } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from '../hooks/useAuth'
import type { Role } from '../types/auth'
import { hasAnyRole } from '../utils/roles'

interface ProtectedRouteProps {
  /** If given, the user needs at least one of these roles (admins always pass). */
  roles?: readonly Role[]
  /** Content to protect; defaults to the nested routes (<Outlet />). */
  children?: ReactNode
}

/**
 * Guards pages that need a logged-in user:
 * - while the session is being restored: shows a loading screen,
 * - not logged in: redirects to /login (and back here after logging in),
 * - wrong role: redirects to /forbidden.
 */
export function ProtectedRoute({ roles, children }: ProtectedRouteProps) {
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return (
      <div role="status" className="flex min-h-screen items-center justify-center text-slate-500">
        Loading…
      </div>
    )
  }
  if (status === 'anonymous' || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  if (roles && !hasAnyRole(user, roles)) {
    return <Navigate to="/forbidden" replace />
  }
  return children ?? <Outlet />
}
