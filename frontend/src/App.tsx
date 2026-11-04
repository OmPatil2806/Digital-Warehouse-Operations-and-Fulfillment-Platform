import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter } from 'react-router'

import { AuthProvider } from './context/AuthProvider'
import { ToastProvider } from './context/ToastProvider'
import { createQueryClient } from './lib/queryClient'
import { AppRoutes } from './routes/AppRoutes'

export default function App() {
  const [queryClient] = useState(createQueryClient) // one cache for the whole app

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
