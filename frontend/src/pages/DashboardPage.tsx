import { useEffect, useState } from 'react'

import { getErrorMessage } from '../api/apiClient'
import { getHealth } from '../api/healthApi'
import { HealthStatusCard, type HealthState } from '../components/common/HealthStatusCard'
import { useAuth } from '../hooks/useAuth'

/** Home page after login. Phase 2 placeholder: greeting + system status. */
export default function DashboardPage() {
  const { user, logout } = useAuth()
  const [health, setHealth] = useState<HealthState>({ kind: 'loading' })
  // Incrementing this re-runs the health check effect ("Check again" button)
  const [checkCount, setCheckCount] = useState(0)

  useEffect(() => {
    let ignore = false // avoid updating state from an outdated request

    getHealth()
      .then((data) => {
        if (!ignore) setHealth({ kind: 'online', data })
      })
      .catch((error: unknown) => {
        if (!ignore) setHealth({ kind: 'offline', message: getErrorMessage(error) })
      })

    return () => {
      ignore = true
    }
  }, [checkCount])

  const handleRefresh = () => {
    setHealth({ kind: 'loading' })
    setCheckCount((count) => count + 1)
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Welcome, {user?.full_name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            Signed in as {user?.email} · roles: {user?.roles.join(', ')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void logout()}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-100"
        >
          Log out
        </button>
      </div>

      <h2 className="mt-10 text-lg font-semibold">System status</h2>
      <div className="mt-4 max-w-md">
        <HealthStatusCard state={health} onRefresh={handleRefresh} />
      </div>
    </main>
  )
}
