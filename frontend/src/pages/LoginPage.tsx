import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate, type Location } from 'react-router'

import { getErrorMessage } from '../api/apiClient'
import { useAuth } from '../hooks/useAuth'

/** Where to go after logging in: the page the user originally asked for, or home. */
function redirectTarget(location: Location): string {
  const from = (location.state as { from?: Location } | null)?.from
  return from ? `${from.pathname}${from.search}${from.hash}` : '/'
}

/**
 * Minimal login page (Phase 2, Step 6).
 * Step 7 replaces it with the final design and React Hook Form + Zod validation.
 */
export default function LoginPage() {
  const { status, login } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (status === 'authenticated') return <Navigate to={redirectTarget(location)} replace />

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setSubmitting(true)
    setError(null)
    try {
      await login({ email: String(form.get('email')), password: String(form.get('password')) })
      void navigate(redirectTarget(location), { replace: true })
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="mx-auto mt-24 w-full max-w-sm px-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <form onSubmit={(event) => void handleSubmit(event)} className="mt-6 space-y-4">
        <label className="block text-sm font-medium">
          Email
          <input
            name="email"
            type="email"
            required
            autoComplete="email"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            name="password"
            type="password"
            required
            autoComplete="current-password"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-blue-700 px-4 py-2 font-medium text-white disabled:opacity-50"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
