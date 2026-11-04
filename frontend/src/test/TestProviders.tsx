import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { ToastProvider } from '../context/ToastProvider'

/** A fresh query cache (no retries, so errors show at once) and toasts for each test. */
export function TestProviders({ children }: { children: ReactNode }) {
  // useState: the cache must survive re-renders, exactly like in App.tsx.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      }),
  )
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  )
}
