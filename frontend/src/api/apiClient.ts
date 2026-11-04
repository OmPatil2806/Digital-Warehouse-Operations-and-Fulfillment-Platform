import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'

import type { TokenResponse } from '../types/auth'
import { tokenStore } from './tokenStore'

/** Backend base URL, configured through VITE_API_BASE_URL in the project .env */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

const REFRESH_PATH = '/auth/refresh'
/** Requests that must never trigger an automatic refresh-and-retry. */
const NO_RETRY_PATHS = ['/auth/login', REFRESH_PATH, '/auth/logout']

const baseConfig: AxiosRequestConfig = {
  baseURL: API_BASE_URL,
  timeout: 10_000,
  headers: { 'Content-Type': 'application/json' },
  // Send/receive the httpOnly refresh-token cookie on cross-origin calls
  // (frontend on :5173, API on :8000).
  withCredentials: true,
}

/** Shared Axios instance used by every API module. */
export const apiClient = axios.create(baseConfig)

/**
 * Separate instance for the refresh call itself, without the interceptors below,
 * so a failing refresh can never trigger another refresh.
 */
export const refreshClient = axios.create(baseConfig)

// ------------------------------------------------------------------------- auth failure
type AuthFailureHandler = () => void
let onAuthFailure: AuthFailureHandler | null = null

/** Called (by AuthProvider) to be notified when the session can no longer be renewed. */
export function setAuthFailureHandler(handler: AuthFailureHandler | null): void {
  onAuthFailure = handler
}

// ---------------------------------------------------------------- single-flight refresh
let refreshPromise: Promise<string> | null = null

/**
 * Get a new access token using the refresh-token cookie.
 *
 * If several requests need a refresh at the same time, they all share ONE request.
 * This matters: the backend rotates refresh tokens, and a second refresh with the
 * already-used cookie would look like token theft and log the user out everywhere.
 */
export function refreshAccessToken(): Promise<string> {
  refreshPromise ??= refreshClient
    .post<TokenResponse>(REFRESH_PATH)
    .then(({ data }) => {
      tokenStore.set(data.access_token)
      return data.access_token
    })
    .finally(() => {
      refreshPromise = null
    })
  return refreshPromise
}

// --------------------------------------------------------------------------- interceptors
apiClient.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!(error instanceof AxiosError) || error.response?.status !== 401 || !error.config) {
      throw error
    }
    const config = error.config as RetryableConfig
    const isAuthCall = NO_RETRY_PATHS.some((path) => config.url?.endsWith(path))
    if (config._retried || isAuthCall) throw error

    config._retried = true
    try {
      const token = await refreshAccessToken()
      config.headers.set('Authorization', `Bearer ${token}`)
    } catch {
      tokenStore.clear()
      onAuthFailure?.()
      throw error // report the original 401 to the caller
    }
    return apiClient(config)
  },
)

// ------------------------------------------------------------------------------- errors
/** Convert any Axios/network error into a readable message for the UI. */
export function getErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.response) {
      const detail = (error.response.data as { detail?: unknown } | undefined)?.detail
      return typeof detail === 'string' ? detail : `Request failed (${error.response.status})`
    }
    if (error.code === 'ECONNABORTED') return 'Request timed out'
    return 'Cannot reach the server'
  }
  return error instanceof Error ? error.message : 'Unexpected error'
}
