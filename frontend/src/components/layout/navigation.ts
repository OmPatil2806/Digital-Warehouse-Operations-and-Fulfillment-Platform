import {
  BarChart3,
  Bell,
  Boxes,
  BrainCircuit,
  ClipboardList,
  FileText,
  LayoutDashboard,
  Package,
  ScrollText,
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
  /** Show a live counter next to the link. */
  badge?: 'unresolved-alerts'
}

export interface NavSection {
  title: string
  items: NavItem[]
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Overview',
    items: [{ label: 'Dashboard', to: '/', icon: LayoutDashboard }],
  },
  {
    title: 'Warehouse',
    items: [
      {
        label: 'Products',
        to: '/products',
        icon: Package,
        roles: ['manager', 'staff'],
      },
      {
        label: 'Suppliers',
        to: '/suppliers',
        icon: Truck,
        roles: ['manager'],
      },
      {
        label: 'Warehouse layout',
        to: '/warehouse',
        icon: Warehouse,
        roles: ['manager', 'staff'],
      },
      {
        label: 'Inventory',
        to: '/inventory',
        icon: Boxes,
        roles: ['manager', 'staff'],
      },
      {
        label: 'Purchase orders',
        to: '/purchase-orders',
        icon: FileText,
        roles: ['manager', 'staff'],
      },
    ],
  },
  {
    title: 'Orders',
    items: [
      { label: 'Orders', to: '/orders', icon: ShoppingCart },
      {
        label: 'Fulfillment',
        to: '/fulfillment',
        icon: ClipboardList,
        roles: ['manager', 'staff'],
      },
      {
        label: 'Shipments',
        to: '/shipments',
        icon: Truck,
        roles: ['manager', 'staff', 'customer'],
      },
    ],
  },
  {
    title: 'Insights',
    items: [
      {
        label: 'Alerts',
        to: '/alerts',
        icon: Bell,
        roles: ['manager', 'staff'],
        badge: 'unresolved-alerts',
      },
      {
        label: 'Reports',
        to: '/reports',
        icon: BarChart3,
        roles: ['manager', 'staff'],
      },
      {
        label: 'ML insights',
        to: '/ml-insights',
        icon: BrainCircuit,
        roles: ['manager', 'staff'],
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      {
        label: 'Users',
        to: '/users',
        icon: Users,
        roles: ['admin'],
      },
      {
        label: 'Audit log',
        to: '/audit-log',
        icon: ScrollText,
        roles: ['admin'],
      },
    ],
  },
]
