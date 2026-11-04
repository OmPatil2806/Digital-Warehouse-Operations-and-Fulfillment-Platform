import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { loggedInAs, makeAuth, renderWithAuth } from '../test/renderWithAuth'
import { ProtectedRoute } from './ProtectedRoute'

const SECRET = <p>secret page</p>
const routes = { '/login': <p>login page</p>, '/forbidden': <p>forbidden page</p> }

describe('ProtectedRoute', () => {
  it('shows a loading screen while the session is being restored', () => {
    renderWithAuth(<ProtectedRoute>{SECRET}</ProtectedRoute>, {
      auth: makeAuth({ status: 'loading' }),
      routes,
    })

    expect(screen.getByRole('status')).toHaveTextContent('Loading…')
    expect(screen.queryByText('secret page')).not.toBeInTheDocument()
  })

  it('redirects anonymous users to /login', () => {
    renderWithAuth(<ProtectedRoute>{SECRET}</ProtectedRoute>, { routes })

    expect(screen.getByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('secret page')).not.toBeInTheDocument()
  })

  it('shows the page to any logged-in user when no roles are required', () => {
    renderWithAuth(<ProtectedRoute>{SECRET}</ProtectedRoute>, {
      auth: loggedInAs('customer'),
      routes,
    })

    expect(screen.getByText('secret page')).toBeInTheDocument()
  })

  it.each([
    { roles: ['manager'] as const, expected: 'secret page' },
    { roles: ['staff', 'manager'] as const, expected: 'secret page' },
    { roles: ['admin'] as const, expected: 'secret page' }, // admins pass every check
    { roles: ['staff'] as const, expected: 'forbidden page' },
    { roles: ['customer'] as const, expected: 'forbidden page' },
  ])('user with roles $roles → $expected', ({ roles, expected }) => {
    renderWithAuth(<ProtectedRoute roles={['manager']}>{SECRET}</ProtectedRoute>, {
      auth: loggedInAs(...roles),
      routes,
    })

    expect(screen.getByText(expected)).toBeInTheDocument()
  })
})
