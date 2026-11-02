import type { HealthResponse } from '../../types/health'

export type HealthState =
  | { kind: 'loading' }
  | { kind: 'online'; data: HealthResponse }
  | { kind: 'offline'; message: string }

interface HealthStatusCardProps {
  state: HealthState
  onRefresh: () => void
}

const BADGE_STYLES = {
  loading: 'bg-slate-100 text-slate-600',
  online: 'bg-emerald-100 text-emerald-700',
  degraded: 'bg-amber-100 text-amber-700',
  offline: 'bg-red-100 text-red-700',
} as const

export function HealthStatusCard({ state, onRefresh }: HealthStatusCardProps) {
  const variant =
    state.kind === 'online' && state.data.status !== 'ok'
      ? 'degraded'
      : (state.kind as keyof typeof BADGE_STYLES)

  const label = {
    loading: 'Checking…',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
  }[variant]

  return (
    <section
      aria-label="Backend status"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Backend API</h3>
        <span
          data-testid="backend-status"
          className={`rounded-full px-3 py-1 text-xs font-semibold ${BADGE_STYLES[variant]}`}
        >
          {label}
        </span>
      </div>

      {state.kind === 'online' && (
        <dl className="mt-4 grid grid-cols-2 gap-y-2 text-sm">
          <dt className="text-slate-500">Database</dt>
          <dd className="font-medium">
            {state.data.database === 'ok' ? 'Connected' : 'Unavailable'}
          </dd>
          <dt className="text-slate-500">Version</dt>
          <dd className="font-medium">{state.data.version}</dd>
          <dt className="text-slate-500">Environment</dt>
          <dd className="font-medium">{state.data.environment}</dd>
        </dl>
      )}

      {state.kind === 'offline' && (
        <p className="mt-4 text-sm text-red-700">
          {state.message}. Start the backend with <code>uvicorn app.main:app --reload</code>.
        </p>
      )}

      <button
        type="button"
        onClick={onRefresh}
        disabled={state.kind === 'loading'}
        className="mt-5 rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
      >
        Check again
      </button>
    </section>
  )
}
