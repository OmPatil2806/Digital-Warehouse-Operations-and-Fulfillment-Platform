import { createContext } from 'react'

export type ToastTone = 'success' | 'error' | 'info'

/** How long a toast stays visible (errors stay a little longer). */
export const TOAST_DURATION_MS = { success: 4000, info: 4000, error: 7000 } as const

export interface Toast {
  id: number
  tone: ToastTone
  message: string
}

export interface ToastContextValue {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
  dismiss: (id: number) => void
}

export const ToastContext = createContext<ToastContextValue | null>(null)
