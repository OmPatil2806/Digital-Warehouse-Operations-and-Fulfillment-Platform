import { X } from 'lucide-react'
import { useState } from 'react'
import { Outlet } from 'react-router'

import { Sidebar } from '../components/layout/Sidebar'
import { Topbar } from '../components/layout/Topbar'

/** Layout for all logged-in pages: sidebar + top bar + page content. */
export default function DashboardLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const closeMenu = () => setMobileMenuOpen(false)

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="fixed inset-y-0 w-64">
          <Sidebar />
        </div>
      </aside>

      {/* Mobile sidebar (slide-over) */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Close navigation menu"
            onClick={closeMenu}
            className="absolute inset-0 bg-slate-900/50"
          />
          <div className="relative h-full w-64">
            <Sidebar onNavigate={closeMenu} />
            <button
              type="button"
              onClick={closeMenu}
              aria-label="Close navigation menu"
              className="absolute top-4 right-3 rounded-lg p-1.5 text-slate-400 hover:bg-slate-800"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenuClick={() => setMobileMenuOpen(true)} />
        <main className="flex-1 px-4 py-8 sm:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
