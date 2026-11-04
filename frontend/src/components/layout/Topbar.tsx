import { LogOut, Menu } from 'lucide-react'

import { useAuth } from '../../hooks/useAuth'
import type { Role } from '../../types/auth'

const ROLE_STYLES: Record<Role, string> = {
  admin: 'bg-purple-100 text-purple-700',
  manager: 'bg-blue-100 text-blue-700',
  staff: 'bg-emerald-100 text-emerald-700',
  customer: 'bg-amber-100 text-amber-700',
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

interface TopbarProps {
  onMenuClick: () => void
}

/** Top bar: mobile menu button, current user, role badges and logout. */
export function Topbar({ onMenuClick }: TopbarProps) {
  const { user, logout } = useAuth()

  return (
    <header className="flex h-16 items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        aria-label="Open navigation menu"
        className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden"
      >
        <Menu size={20} aria-hidden="true" />
      </button>
      <div className="hidden lg:block" />

      {user && (
        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-sm leading-tight font-medium">{user.full_name}</p>
            <p className="text-xs text-slate-500">{user.email}</p>
          </div>
          <ul aria-label="Your roles" className="flex gap-1">
            {user.roles.map((role) => (
              <li
                key={role}
                className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${ROLE_STYLES[role]}`}
              >
                {role}
              </li>
            ))}
          </ul>
          <div
            aria-hidden="true"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-700"
          >
            {initials(user.full_name)}
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
          >
            <LogOut size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Log out</span>
            <span className="sr-only sm:hidden">Log out</span>
          </button>
        </div>
      )}
    </header>
  )
}
