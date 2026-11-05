import {
  Bell,
  Boxes,
  BrainCircuit,
  ClipboardList,
  LayoutDashboard,
  Package,
  Settings,
  ShoppingCart,
  Truck,
  Users,
  Warehouse,
  type LucideIcon,
} from 'lucide-react'

import type { Role } from '../../types/auth'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  /** Who sees the link. Omit for "every logged-in user". Admins always see everything. */
  roles?: readonly Role[]
  /** Phase in which the page is (or will be) built. */
  availableInPhase: number
  /** True once the page exists. Other items are shown disabled with their phase. */
  ready?: boolean
}

export interface NavSection {
  title: string
  items: NavItem[]
}

/** True if the page behind a navigation item exists yet. */
export function isReady(item: NavItem): boolean {
  return item.ready === true
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Overview',
    items: [
      { label: 'Dashboard', to: '/', icon: LayoutDashboard, availableInPhase: 2, ready: true },
    ],
  },
  {
    title: 'Warehouse',
    items: [
      {
        label: 'Products',
        to: '/products',
        icon: Package,
        roles: ['manager', 'staff'],
        availableInPhase: 3,
        ready: true,
      },
      {
        label: 'Suppliers',
        to: '/suppliers',
        icon: Truck,
        roles: ['manager'],
        availableInPhase: 3,
        ready: true,
      },
      {
        label: 'Warehouse layout',
        to: '/warehouse',
        icon: Warehouse,
        roles: ['manager', 'staff'],
        availableInPhase: 3,
        ready: true,
      },
      {
        label: 'Inventory',
        to: '/inventory',
        icon: Boxes,
        roles: ['manager', 'staff'],
        availableInPhase: 4,
      },
    ],
  },
  {
    title: 'Orders',
    items: [
      { label: 'Orders', to: '/orders', icon: ShoppingCart, availableInPhase: 5 },
      {
        label: 'Fulfillment',
        to: '/fulfillment',
        icon: ClipboardList,
        roles: ['manager', 'staff'],
        availableInPhase: 5,
      },
      {
        label: 'Shipments',
        to: '/shipments',
        icon: Truck,
        roles: ['manager', 'staff', 'customer'],
        availableInPhase: 5,
      },
    ],
  },
  {
    title: 'Insights',
    items: [
      { label: 'Alerts', to: '/alerts', icon: Bell, roles: ['manager'], availableInPhase: 6 },
      {
        label: 'ML insights',
        to: '/ml-insights',
        icon: BrainCircuit,
        roles: ['manager'],
        availableInPhase: 9,
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      { label: 'Users', to: '/users', icon: Users, roles: ['admin'], availableInPhase: 3 },
      {
        label: 'Settings',
        to: '/settings',
        icon: Settings,
        roles: ['admin'],
        availableInPhase: 10,
      },
    ],
  },
]
