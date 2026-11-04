import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { loggedInAs, renderWithAuth } from '../../test/renderWithAuth'
import type { Role } from '../../types/auth'
import { Sidebar } from './Sidebar'

function renderSidebar(...roles: Role[]) {
  const onNavigate = vi.fn()
  renderWithAuth(<Sidebar onNavigate={onNavigate} />, { auth: loggedInAs(...roles) })
  return { nav: screen.getByRole('navigation', { name: 'Main navigation' }), onNavigate }
}

/** Labels of all items (enabled links and disabled entries), without phase badges. */
function itemLabels(nav: HTMLElement): string[] {
  return within(nav)
    .getAllByRole('listitem')
    .map((item) => (item.textContent ?? '').replace(/P\d+$/, '').trim())
}

describe('Sidebar', () => {
  it.each<[Role, string[]]>([
    [
      'admin',
      [
        'Dashboard',
        'Products',
        'Suppliers',
        'Warehouse layout',
        'Inventory',
        'Orders',
        'Fulfillment',
        'Shipments',
        'Alerts',
        'ML insights',
        'Users',
        'Settings',
      ],
    ],
    [
      'manager',
      [
        'Dashboard',
        'Products',
        'Suppliers',
        'Warehouse layout',
        'Inventory',
        'Orders',
        'Fulfillment',
        'Shipments',
        'Alerts',
        'ML insights',
      ],
    ],
    [
      'staff',
      [
        'Dashboard',
        'Products',
        'Warehouse layout',
        'Inventory',
        'Orders',
        'Fulfillment',
        'Shipments',
      ],
    ],
    ['customer', ['Dashboard', 'Orders', 'Shipments']],
  ])('%s sees exactly the allowed items', (role, expected) => {
    const { nav } = renderSidebar(role)

    expect(itemLabels(nav)).toEqual(expected)
  })

  it('combines the items of several roles', () => {
    const { nav } = renderSidebar('staff', 'customer')

    expect(itemLabels(nav)).toEqual([
      'Dashboard',
      'Products',
      'Warehouse layout',
      'Inventory',
      'Orders',
      'Fulfillment',
      'Shipments',
    ])
  })

  it('hides section headings that would be empty', () => {
    renderSidebar('customer')

    expect(screen.queryByText('Warehouse')).not.toBeInTheDocument()
    expect(screen.queryByText('Administration')).not.toBeInTheDocument()
    expect(screen.getByText('Orders', { selector: 'p' })).toBeInTheDocument()
  })

  it('only the Dashboard is a link; later-phase pages are disabled with a phase badge', () => {
    const { nav } = renderSidebar('manager')

    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Dashboard'])
    expect(links[0]).toHaveAttribute('href', '/')

    const products = within(nav).getByText('Products').closest('[aria-disabled="true"]')
    expect(products).not.toBeNull()
    expect(products).toHaveAttribute('title', 'Coming in Phase 3')
    expect(products).toHaveTextContent('P3')
  })

  it('marks the current page as active', () => {
    const { nav } = renderSidebar('staff')

    expect(within(nav).getByRole('link', { name: 'Dashboard' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('calls onNavigate when a link is clicked (closes the mobile menu)', async () => {
    const { nav, onNavigate } = renderSidebar('staff')

    await userEvent.setup().click(within(nav).getByRole('link', { name: 'Dashboard' }))

    expect(onNavigate).toHaveBeenCalledOnce()
  })
})
