import { QueryClient } from '@tanstack/react-query'
import { AxiosError } from 'axios'

/** Retry only network problems and server errors (5xx), never 4xx answers. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof AxiosError) {
    const status = error.response?.status
    if (status !== undefined && status < 500) return false
  }
  return failureCount < 2
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000, // data counts as fresh for 30 s: no refetch when revisiting a page
        retry: shouldRetry,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  })
}
