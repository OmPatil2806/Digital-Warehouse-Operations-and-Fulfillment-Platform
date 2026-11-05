import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { setAuthFailureHandler } from '../api/apiClient'
import * as authApi from '../api/authApi'
import type { LoginCredentials, User } from '../types/auth'
import { AuthContext, type AuthContextValue, type AuthStatus } from './authContext'

interface AuthState {
  status: AuthStatus
  user: User | null
  endedByLogout: boolean
}

const ANONYMOUS: AuthState = { status: 'anonymous', user: null, endedByLogout: false }

/** Holds the logged-in user and exposes login/logout to the whole app. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: 'loading',
    user: null,
    endedByLogout: false,
  })

  // On page load: try to restore the session from the httpOnly refresh cookie.
  useEffect(() => {
    let ignore = false
    authApi
      .refreshSession()
      .then(() => authApi.getCurrentUser())
      .then((user) => {
        if (!ignore) setState({ status: 'authenticated', user, endedByLogout: false })
      })
      .catch(() => {
        if (!ignore) setState(ANONYMOUS)
      })
    return () => {
      ignore = true
    }
  }, [])

  // If any API call finds that the session can no longer be renewed, log out locally.
  useEffect(() => {
    setAuthFailureHandler(() => setState(ANONYMOUS))
    return () => setAuthFailureHandler(null)
  }, [])

  const login = useCallback(async (credentials: LoginCredentials) => {
    await authApi.login(credentials)
    const user = await authApi.getCurrentUser()
    setState({ status: 'authenticated', user, endedByLogout: false })
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Server unreachable: the refresh token expires on its own; log out locally anyway.
    }
    setState({ ...ANONYMOUS, endedByLogout: true })
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout }),
    [state, login, logout],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
