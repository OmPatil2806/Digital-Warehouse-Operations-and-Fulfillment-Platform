/**
 * Whole-app flows: the real app (router, auth, layout, pages) against a fake backend.
 *
 * Covers how people get in, around and out: login (and back to the page they asked
 * for), wrong passwords, the role rules for pages and navigation, logout, restoring a
 * session after a page reload, and a session that runs out while the app is open.
 */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import App from '../src/App'
import { PASSWORD, startFakeBackend, type FakeBackend } from './fakeBackend'

let backend: FakeBackend

beforeEach(() => {
  backend = startFakeBackend()
})

afterEach(() => {
  backend.close()
  window.history.pushState({}, '', '/')
})

function open(path: string) {
  window.history.pushState({}, '', path)
  render(<App />)
  return userEvent.setup()
}

async function signIn(
  user: ReturnType<typeof userEvent.setup>,
  email: string,
  password = PASSWORD,
) {
  await user.type(await screen.findByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' })

describe('logging in and out', () => {
  it('sends visitors to login and back to the page they asked for', async () => {
    const user = open('/orders')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')

    await signIn(user, 'manager@example.com', 'wrong-password')
    expect(await screen.findByText('Incorrect email or password')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/login')

    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), PASSWORD)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Orders' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/orders')
  })

  it('logs out, and the next login starts on the dashboard', async () => {
    const user = open('/products')
    await signIn(user, 'manager@example.com')
    expect(await screen.findByRole('heading', { name: 'Products' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(backend.requests).toContain('POST /auth/logout')

    // The next person to log in starts on the dashboard, not on the previous user's page.
    await signIn(user, 'staff@example.com')
    expect(await screen.findByRole('heading', { name: 'Welcome, Sam Staff' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
  })

  it('restores the session after a page reload', async () => {
    backend.rememberSession('staff@example.com')
    open('/inventory')
    expect(await screen.findByRole('heading', { name: /Inventory/ })).toBeInTheDocument()
    expect(backend.requests.slice(0, 2)).toEqual(['POST /auth/refresh', 'GET /auth/me'])
  })

  it('returns to login when the session runs out while the app is open', async () => {
    const user = open('/')
    await signIn(user, 'manager@example.com')
    expect(
      await screen.findByRole('heading', { name: 'Welcome, Maya Manager' }),
    ).toBeInTheDocument()

    backend.expireSession()
    await user.click(within(nav()).getByRole('link', { name: /Products/ }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    // It tried to renew the session once before giving up.
    expect(backend.requests.filter((r) => r === 'POST /auth/refresh').length).toBeGreaterThan(1)
  })
})

describe('roles', () => {
  it('shows each role only its own pages', async () => {
    const user = open('/')
    await signIn(user, 'staff@example.com')
    await screen.findByRole('heading', { name: 'Welcome, Sam Staff' })
    const links = within(nav())
    expect(links.getByRole('link', { name: /Fulfillment/ })).toBeInTheDocument()
    expect(links.queryByRole('link', { name: /Users/ })).toBeNull()
    expect(links.queryByRole('link', { name: /Audit log/ })).toBeNull()
  })

  it('blocks a page the role may not open, even by typing its address', async () => {
    const user = open('/users')
    await signIn(user, 'staff@example.com')
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/forbidden')
  })

  it('keeps customers to their own orders and shipments', async () => {
    const user = open('/')
    await signIn(user, 'customer@example.com')
    await screen.findByRole('heading', { name: 'Welcome, Chris Customer' })
    const links = within(nav())
    expect(links.getByRole('link', { name: /My orders|Orders/ })).toBeInTheDocument()
    expect(links.queryByRole('link', { name: /Products/ })).toBeNull()
    expect(links.queryByRole('link', { name: /ML insights/ })).toBeNull()

    window.history.pushState({}, '', '/ml-insights')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(window.location.pathname).toBe('/forbidden'))
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
  })

  it('lets admins open the admin pages', async () => {
    const user = open('/audit-log')
    await signIn(user, 'admin@example.com')
    expect(await screen.findByRole('heading', { name: /Audit log/ })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/audit-log')
  })
})
