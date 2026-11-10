import { AlertOctagon, AlertTriangle, Info } from 'lucide-react'
import { Link } from 'react-router'

import type { Alert } from '../../types/alerts'
import { formatDateTime } from '../inventory/movementFormat'

const SEVERITY = {
  critical: { icon: AlertOctagon, className: 'text-red-700', label: 'Critical' },
  warning: { icon: AlertTriangle, className: 'text-amber-700', label: 'Warning' },
  info: { icon: Info, className: 'text-blue-700', label: 'Info' },
} as const

/** The newest unresolved alerts, with a link to all of them. */
export function RecentAlerts({
  alerts,
  total,
  isLoading,
  errorMessage,
}: {
  alerts: Alert[] | undefined
  total: number | undefined
  isLoading?: boolean
  errorMessage?: string | null
}) {
  return (
    <section
      aria-labelledby="recent-alerts-heading"
      className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 id="recent-alerts-heading" className="font-medium text-slate-900">
          Latest alerts
        </h3>
        <Link to="/alerts" className="text-xs font-medium text-blue-700 hover:underline">
          {total ? `All ${total} open alerts` : 'All alerts'}
        </Link>
      </div>
      {errorMessage ? (
        <p role="alert" className="text-sm text-red-700">
          {errorMessage}
        </p>
      ) : isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : !alerts?.length ? (
        <p className="text-sm text-slate-500">No open alerts. All good.</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {alerts.map((alert) => {
            const severity = SEVERITY[alert.severity] ?? SEVERITY.info
            const Icon = severity.icon
            return (
              <li key={alert.id} className="flex gap-2 py-2">
                <Icon
                  size={16}
                  className={`mt-0.5 shrink-0 ${severity.className}`}
                  aria-label={severity.label}
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">{alert.title}</p>
                  {alert.message && (
                    <p className="truncate text-xs text-slate-500">{alert.message}</p>
                  )}
                  <p className="text-xs text-slate-400">{formatDateTime(alert.created_at)}</p>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
