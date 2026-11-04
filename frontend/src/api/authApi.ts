import type { LoginCredentials, TokenResponse, User } from '../types/auth'
import { apiClient, refreshAccessToken } from './apiClient'
import { tokenStore } from './tokenStore'

/** Log in; stores the access token in memory (the refresh cookie is set by the server). */
export async function login(credentials: LoginCredentials): Promise<void> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', credentials)
  tokenStore.set(data.access_token)
}

/** Get a fresh access token from the refresh-token cookie (e.g. after a page reload). */
export async function refreshSession(): Promise<void> {
  await refreshAccessToken()
}

/** The currently logged-in user. */
export async function getCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>('/auth/me')
  return data
}

/** Log out on the server (revokes the refresh token) and forget the access token. */
export async function logout(): Promise<void> {
  try {
    await apiClient.post('/auth/logout')
  } finally {
    tokenStore.clear()
  }
}
