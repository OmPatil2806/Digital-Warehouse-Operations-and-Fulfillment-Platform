import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as alertsApi from '../../api/alertsApi'
import { loggedInAs, renderWithAuth } from '../../test/renderWithAuth'
import type { Role } from '../../types/auth'
import { Sidebar } from './Sidebar'

vi.mock('../../api/alertsApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/alertsApi')>()),
  getAlertSummary: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(alertsApi.getAlertSummary).mockResolvedValue({ unresolved: 0 })
})

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
  it('shows the number of unresolved alerts next to Alerts', async () => {
    vi.mocked(alertsApi.getAlertSummary).mockResolvedValue({ unresolved: 6 })
    const { nav } = renderSidebar('staff')

    expect(await within(nav).findByLabelText('6 unresolved alerts')).toHaveTextContent('6')
    expect(within(nav).getByRole('link', { name: /Alerts/ })).toHaveAttribute('href', '/alerts')
  })

  it('shows no badge when nothing needs attention, and none for customers', async () => {
    const { nav } = renderSidebar('manager')
    await vi.waitFor(() => expect(alertsApi.getAlertSummary).toHaveBeenCalled())
    expect(within(nav).queryByLabelText(/unresolved alert/)).not.toBeInTheDocument()
  })

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
        'Audit log',
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
        'Alerts',
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
      'Alerts',
    ])
  })

  it('hides section headings that would be empty', () => {
    renderSidebar('customer')

    expect(screen.queryByText('Warehouse')).not.toBeInTheDocument()
    expect(screen.queryByText('Administration')).not.toBeInTheDocument()
    expect(screen.getByText('Orders', { selector: 'p' })).toBeInTheDocument()
  })

  it('ready pages are links; pages from later steps are disabled with a phase badge', () => {
    const { nav } = renderSidebar('manager')

    const links = within(nav).getAllByRole('link')
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Dashboard', '/'],
      ['Products', '/products'],
      ['Suppliers', '/suppliers'],
      ['Warehouse layout', '/warehouse'],
      ['Inventory', '/inventory'],
      ['Orders', '/orders'],
      ['Fulfillment', '/fulfillment'],
      ['Alerts', '/alerts'],
    ])

    const shipments = within(nav).getByText('Shipments').closest('[aria-disabled="true"]')
    expect(shipments).not.toBeNull()
    expect(shipments).toHaveAttribute('title', 'Coming in Phase 5')
    expect(shipments).toHaveTextContent('P5')
  })

  it('keeps a section highlighted on its detail pages', () => {
    renderWithAuth(<Sidebar />, { auth: loggedInAs('manager'), path: '/products/12' })

    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(within(nav).getByRole('link', { name: 'Products' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current')
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
