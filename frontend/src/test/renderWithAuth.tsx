import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { vi } from 'vitest'

import { AuthContext, type AuthContextValue } from '../context/authContext'
import type { Role, User } from '../types/auth'
import { TestProviders } from './TestProviders'

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    email: 'alex@example.com',
    full_name: 'Alex Example',
    is_active: true,
    roles: ['customer'],
    last_login_at: '2026-11-04T08:00:00Z',
    created_at: '2026-11-01T08:00:00Z',
    updated_at: '2026-11-04T08:00:00Z',
    ...overrides,
  }
}

export function makeAuth(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    status: 'anonymous',
    user: null,
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

export function loggedInAs(...roles: Role[]): AuthContextValue {
  return makeAuth({ status: 'authenticated', user: makeUser({ roles }) })
}

interface Options {
  auth?: AuthContextValue
  /** URL the router starts at. */
  path?: string
  /** Router location state, e.g. { from: { pathname: '/orders' } } after a redirect to login. */
  state?: unknown
  /** Extra routes, e.g. to detect redirects: { '/login': <p>login page</p> } */
  routes?: Record<string, ReactElement>
}

/** Render `ui` at `path` inside a router, with a fake auth context. */
export function renderWithAuth(ui: ReactElement, options: Options = {}) {
  const { auth = makeAuth(), path = '/', state, routes = {} } = options
  return render(
    <TestProviders>
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={[{ pathname: path, state }]}>
          <Routes>
            <Route path={path} element={ui} />
            {Object.entries(routes).map(([routePath, element]) => (
              <Route key={routePath} path={routePath} element={element} />
            ))}
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </TestProviders>,
  )
}
