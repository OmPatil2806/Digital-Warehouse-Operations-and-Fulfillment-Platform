import { PackageCheck } from 'lucide-react'
import { NavLink } from 'react-router'

import { useAuth } from '../../hooks/useAuth'
import { hasAnyRole } from '../../utils/roles'
import { isReady, NAV_SECTIONS, type NavItem, type NavSection } from './navigation'

interface SidebarProps {
  /** Called after a link is clicked (closes the mobile menu). */
  onNavigate?: () => void
}

function visibleSections(sections: NavSection[], canSee: (item: NavItem) => boolean) {
  return sections
    .map((section) => ({ ...section, items: section.items.filter(canSee) }))
    .filter((section) => section.items.length > 0)
}

/** Role-aware navigation. Pages from later phases are listed but disabled. */
export function Sidebar({ onNavigate }: SidebarProps) {
  const { user } = useAuth()
  const sections = visibleSections(
    NAV_SECTIONS,
    (item) => !item.roles || hasAnyRole(user, item.roles),
  )

  return (
    <div className="flex h-full flex-col bg-slate-900 text-slate-300">
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white">
          <PackageCheck size={20} aria-hidden="true" />
        </div>
        <div>
          <p className="text-sm leading-tight font-semibold text-white">Digital Warehouse</p>
          <p className="text-xs text-slate-400">Operations &amp; Fulfillment</p>
        </div>
      </div>

      <nav aria-label="Main navigation" className="flex-1 space-y-6 overflow-y-auto px-3 pb-6">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="px-3 pb-2 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">
              {section.title}
            </p>
            <ul className="space-y-1">
              {section.items.map((item) => (
                <li key={item.to}>
                  <SidebarLink item={item} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  )
}

function SidebarLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const Icon = item.icon
  const base = 'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium'

  if (!isReady(item)) {
    return (
      <span
        aria-disabled="true"
        title={`Coming in Phase ${item.availableInPhase}`}
        className={`${base} cursor-not-allowed text-slate-500`}
      >
        <Icon size={18} aria-hidden="true" />
        <span className="flex-1">{item.label}</span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">
          P{item.availableInPhase}
        </span>
      </span>
    )
  }

  return (
    <NavLink
      to={item.to}
      end={item.to === '/'} // other links stay active on their detail pages (/products/12)
      onClick={onNavigate}
      className={({ isActive }) =>
        `${base} transition-colors ${
          isActive ? 'bg-blue-600 text-white' : 'hover:bg-slate-800 hover:text-white'
        }`
      }
    >
      <Icon size={18} aria-hidden="true" />
      {item.label}
    </NavLink>
  )
}
