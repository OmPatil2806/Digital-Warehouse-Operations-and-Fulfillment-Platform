import { createContext } from 'react'

import type { LoginCredentials, User } from '../types/auth'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  /** 'loading' while the saved session is being restored after a page load. */
  status: AuthStatus
  user: User | null
  login: (credentials: LoginCredentials) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
