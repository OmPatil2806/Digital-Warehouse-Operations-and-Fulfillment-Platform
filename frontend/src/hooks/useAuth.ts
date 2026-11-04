import { useContext } from 'react'

import { AuthContext, type AuthContextValue } from '../context/authContext'

/** Access the current user and login/logout. Must be used inside <AuthProvider>. */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
