import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../api/healthApi'
import { AuthContext, type AuthContextValue } from '../context/authContext'
import { makeHealthResponse } from '../test/fixtures'
import { loggedInAs, makeAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import { AppRoutes } from './AppRoutes'

vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))

function renderApp(path: string, auth: AuthContextValue) {
  return render(
    <TestProviders>
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthContext>
    </TestProviders>,
  )
}

beforeEach(() => {
  vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
})

describe('AppRoutes (whole app navigation)', () => {
  it('sends anonymous visitors of / to the login page', () => {
    renderApp('/', makeAuth())

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  })

  it('sends anonymous visitors of unknown pages to login too (no information leak)', () => {
    renderApp('/secret-admin-page', makeAuth())

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows the dashboard inside the sidebar layout after login', async () => {
    renderApp('/', loggedInAs('manager'))

    expect(await screen.findByRole('heading', { name: /Welcome/ })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it('shows the 404 page inside the layout for unknown URLs', () => {
    renderApp('/does-not-exist', loggedInAs('staff'))

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
  })

  it('shows the 403 page inside the layout', () => {
    renderApp('/forbidden', loggedInAs('customer'))

    expect(screen.getByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
  })

  it('redirects logged-in users away from /login', async () => {
    renderApp('/login', loggedInAs('admin'))

    expect(await screen.findByRole('heading', { name: /Welcome/ })).toBeInTheDocument()
  })

  it('"Back to dashboard" on the 404 page goes home', async () => {
    renderApp('/nowhere', loggedInAs('staff'))

    await userEvent.setup().click(screen.getByRole('link', { name: 'Back to dashboard' }))

    expect(await screen.findByRole('heading', { name: /Welcome/ })).toBeInTheDocument()
  })

  it('the mobile menu opens and closes', async () => {
    const user = userEvent.setup()
    renderApp('/', loggedInAs('staff'))

    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Close navigation menu' })[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
