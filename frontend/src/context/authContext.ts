import { createContext } from 'react'

import type { LoginCredentials, User } from '../types/auth'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  /** 'loading' while the saved session is being restored after a page load. */
  status: AuthStatus
  user: User | null
  /**
   * True when the session ended because the user clicked "Log out" (not because it expired).
   * Then the next login starts fresh instead of returning to the previous user's page.
   */
  endedByLogout: boolean
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
