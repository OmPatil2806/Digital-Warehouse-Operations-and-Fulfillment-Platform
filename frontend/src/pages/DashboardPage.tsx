import { lazy, Suspense } from 'react'

import { getHealth } from '../api/healthApi'
import { HealthStatusCard, type HealthState } from '../components/common/HealthStatusCard'
import { isReady, NAV_SECTIONS } from '../components/layout/navigation'
import { isOrderManager, isWarehouseRole } from '../components/orders/orderFormat'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { hasAnyRole } from '../utils/roles'

// The dashboards (and the chart library) load on first use, so the login page stays small.
const overviews = () => import('../components/dashboard/RoleOverviews')
const ManagerOverview = lazy(() => overviews().then((m) => ({ default: m.ManagerOverview })))
const StaffOverview = lazy(() => overviews().then((m) => ({ default: m.StaffOverview })))
const CustomerOverview = lazy(() => overviews().then((m) => ({ default: m.CustomerOverview })))

/**
 * Home page after login: a dashboard for the user's role (managers: KPIs and trends for
 * a period; staff: today's work; customers: their orders and parcels), then the
 * user's modules and the system status.
 */
export default function DashboardPage() {
  const { user } = useAuth()
  const healthQuery = useApiQuery(['health'], getHealth)
  const health: HealthState =
    healthQuery.isFetching || healthQuery.isPending
      ? { kind: 'loading' }
      : healthQuery.data
        ? { kind: 'online', data: healthQuery.data }
        : { kind: 'offline', message: healthQuery.errorMessage ?? 'Unknown error' }

  const modules = NAV_SECTIONS.flatMap((section) => section.items).filter(
    (item) => item.to !== '/' && (!item.roles || hasAnyRole(user, item.roles)),
  )

  const manager = isOrderManager(user)
  const staff = !manager && isWarehouseRole(user)
  const intro = manager
    ? 'How the warehouse is doing: stock, orders, deliveries and suppliers.'
    : staff
      ? "Today's work on the floor."
      : 'Your recent orders and parcels.'

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="text-2xl font-semibold">Welcome, {user?.full_name}</h1>
      <p className="mt-1 text-sm text-slate-500">{intro}</p>

      <div className="mt-6">
        <Suspense fallback={<p className="text-sm text-slate-500">Loading the dashboard…</p>}>
          {manager ? <ManagerOverview /> : staff ? <StaffOverview /> : <CustomerOverview />}
        </Suspense>
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-2">
        <section
          aria-labelledby="modules-heading"
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h2 id="modules-heading" className="font-medium">
            Your modules
          </h2>
          <ul className="mt-4 space-y-2 text-sm">
            {modules.map((item) => (
              <li key={item.label} className="flex items-center gap-3">
                <item.icon size={16} className="text-slate-400" aria-hidden="true" />
                <span className="flex-1">{item.label}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    isReady(item)
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-100 text-slate-500'
                  }`}
                >
                  {isReady(item) ? 'Available' : `Phase ${item.availableInPhase}`}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <div>
          <HealthStatusCard state={health} onRefresh={() => void healthQuery.refetch()} />
        </div>
      </div>
    </div>
  )
}
