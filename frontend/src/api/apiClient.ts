import axios, { AxiosError } from 'axios'

/** Backend base URL, configured through VITE_API_BASE_URL in the project .env */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

/** Single, shared Axios instance used by every API module. */
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10_000,
  headers: { 'Content-Type': 'application/json' },
})

// From Phase 2: a request interceptor will attach the JWT access token here.

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
