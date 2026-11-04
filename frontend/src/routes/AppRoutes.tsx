import { Route, Routes } from 'react-router'

import AuthLayout from '../layouts/AuthLayout'
import DashboardLayout from '../layouts/DashboardLayout'
import DashboardPage from '../pages/DashboardPage'
import ForbiddenPage from '../pages/ForbiddenPage'
import LoginPage from '../pages/LoginPage'
import NotFoundPage from '../pages/NotFoundPage'
import { ProtectedRoute } from './ProtectedRoute'

/**
 * All page routes of the application.
 *
 * Role-restricted pages (from Phase 3 on) are wrapped like this:
 *   <Route element={<ProtectedRoute roles={['manager']} />}>
 *     <Route path="/suppliers" element={<SuppliersPage />} />
 *   </Route>
 */
export function AppRoutes() {
  return (
    <Routes>
      {/* Public pages */}
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>

      {/* Any logged-in user, inside the sidebar layout */}
      <Route element={<ProtectedRoute />}>
        <Route element={<DashboardLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="/forbidden" element={<ForbiddenPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
