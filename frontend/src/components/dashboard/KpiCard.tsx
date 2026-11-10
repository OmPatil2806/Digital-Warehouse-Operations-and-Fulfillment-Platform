import { AlertOctagon, AlertTriangle, CheckCircle2, CircleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import type { StatusTone } from './chartTheme'

const STATUS_STYLE: Record<StatusTone, { icon: typeof CheckCircle2; className: string }> = {
  good: { icon: CheckCircle2, className: 'text-green-700' },
  warning: { icon: AlertTriangle, className: 'text-amber-700' },
  serious: { icon: CircleAlert, className: 'text-orange-700' },
  critical: { icon: AlertOctagon, className: 'text-red-700' },
}

/**
 * One headline number. A status is shown as an icon plus words (never colour
 * alone); `detail` explains the number or puts it in context.
 */
export function KpiCard({
  label,
  value,
  detail,
  status,
  isLoading = false,
}: {
  label: string
  value: ReactNode
  detail?: ReactNode
  status?: { tone: StatusTone; label: string }
  isLoading?: boolean
}) {
  const style = status && STATUS_STYLE[status.tone]
  const Icon = style?.icon
  return (
    <section
      aria-label={label}
      aria-busy={isLoading}
      className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <h3 className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</h3>
      {isLoading ? (
        <div className="mt-2 h-8 w-24 animate-pulse rounded bg-slate-100" aria-hidden="true" />
      ) : (
        <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      )}
      {!isLoading && (status || detail) && (
        <div className="mt-1 space-y-0.5 text-xs text-slate-500">
          {status && Icon && (
            <p className={`flex items-center gap-1 font-medium ${style.className}`}>
              <Icon size={14} aria-hidden="true" />
              {status.label}
            </p>
          )}
          {detail && <p>{detail}</p>}
        </div>
      )}
    </section>
  )
}
