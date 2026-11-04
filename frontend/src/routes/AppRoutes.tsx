import { Route, Routes } from 'react-router'

import DashboardPage from '../pages/DashboardPage'
import ForbiddenPage from '../pages/ForbiddenPage'
import LoginPage from '../pages/LoginPage'
import NotFoundPage from '../pages/NotFoundPage'
import { ProtectedRoute } from './ProtectedRoute'

/** All page routes of the application. */
export function AppRoutes() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />

      {/* Any logged-in user */}
      <Route element={<ProtectedRoute />}>
        <Route index element={<DashboardPage />} />
        <Route path="/forbidden" element={<ForbiddenPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
