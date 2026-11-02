import { useEffect, useState } from 'react'

import { getErrorMessage } from './api/apiClient'
import { getHealth } from './api/healthApi'
import { HealthStatusCard, type HealthState } from './components/common/HealthStatusCard'

export default function App() {
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
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-700 font-bold text-white">
            W
          </div>
          <div>
            <h1 className="text-lg leading-tight font-semibold">Digital Warehouse</h1>
            <p className="text-xs text-slate-500">Operations &amp; Fulfillment Platform</p>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
        <h2 className="text-2xl font-semibold">System status</h2>
        <p className="mt-1 text-sm text-slate-500">
          Phase 1 skeleton: the frontend checks that the backend API and database are reachable.
        </p>

        <div className="mt-6 max-w-md">
          <HealthStatusCard state={health} onRefresh={handleRefresh} />
        </div>
      </main>

      <footer className="border-t border-slate-200 py-4 text-center text-xs text-slate-500">
        Digital Warehouse Operations and Fulfillment Platform · v0.1.0
      </footer>
    </div>
  )
}
