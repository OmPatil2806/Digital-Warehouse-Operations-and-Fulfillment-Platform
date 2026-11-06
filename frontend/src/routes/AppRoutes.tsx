import { lazy } from 'react'
import { Route, Routes } from 'react-router'

import AuthLayout from '../layouts/AuthLayout'
import DashboardLayout from '../layouts/DashboardLayout'
import DashboardPage from '../pages/DashboardPage'
import ForbiddenPage from '../pages/ForbiddenPage'
import LoginPage from '../pages/LoginPage'
import NotFoundPage from '../pages/NotFoundPage'
import { ProtectedRoute } from './ProtectedRoute'

// Loaded on first visit (code splitting): the login page stays small and fast.
// DashboardLayout shows a loading message (only in the page area) while they load.
const ProductsPage = lazy(() => import('../pages/ProductsPage'))
const ProductDetailPage = lazy(() => import('../pages/ProductDetailPage'))
const SuppliersPage = lazy(() => import('../pages/SuppliersPage'))
const SupplierDetailPage = lazy(() => import('../pages/SupplierDetailPage'))
const WarehouseLayoutPage = lazy(() => import('../pages/WarehouseLayoutPage'))
const UsersPage = lazy(() => import('../pages/UsersPage'))
const InventoryPage = lazy(() => import('../pages/InventoryPage'))
const CycleCountPage = lazy(() => import('../pages/CycleCountPage'))
const AlertsPage = lazy(() => import('../pages/AlertsPage'))
const OrdersPage = lazy(() => import('../pages/OrdersPage'))
const OrderDetailPage = lazy(() => import('../pages/OrderDetailPage'))
const AuditLogPage = lazy(() => import('../pages/AuditLogPage'))

/**
 * All page routes of the application.
 * Role checks here only hide pages; the backend enforces the same rules on every request.
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
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/orders/:orderId" element={<OrderDetailPage />} />

          {/* Warehouse roles (admin, manager, staff) */}
          <Route element={<ProtectedRoute roles={['manager', 'staff']} />}>
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/products/:productId" element={<ProductDetailPage />} />
            <Route path="/suppliers" element={<SuppliersPage />} />
            <Route path="/suppliers/:supplierId" element={<SupplierDetailPage />} />
            <Route path="/warehouse" element={<WarehouseLayoutPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/inventory/cycle-counts/:countId" element={<CycleCountPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
          </Route>

          {/* Administrators only */}
          <Route element={<ProtectedRoute roles={['admin']} />}>
            <Route path="/users" element={<UsersPage />} />
            <Route path="/audit-log" element={<AuditLogPage />} />
          </Route>

          <Route path="/forbidden" element={<ForbiddenPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
