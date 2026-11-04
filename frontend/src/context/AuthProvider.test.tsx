import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { setAuthFailureHandler } from '../api/apiClient'
import * as authApi from '../api/authApi'
import { useAuth } from '../hooks/useAuth'
import { makeUser } from '../test/renderWithAuth'
import { AuthProvider } from './AuthProvider'

vi.mock('../api/authApi', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  refreshSession: vi.fn(),
  getCurrentUser: vi.fn(),
}))
vi.mock('../api/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/apiClient')>()),
  setAuthFailureHandler: vi.fn(),
}))

const api = vi.mocked(authApi)

/** Shows the auth state and offers login/logout buttons. */
function Probe() {
  const { status, user, login, logout } = useAuth()
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p data-testid="user">{user?.email ?? 'none'}</p>
      <button onClick={() => void login({ email: 'a@example.com', password: 'pw' })}>login</button>
      <button onClick={() => void logout()}>logout</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
}

beforeEach(() => {
  vi.mocked(setAuthFailureHandler).mockReset()
  Object.values(api).forEach((fn) => fn.mockReset())
})

describe('AuthProvider', () => {
  it('starts in "loading" and restores the session from the refresh cookie', async () => {
    api.refreshSession.mockResolvedValue()
    api.getCurrentUser.mockResolvedValue(makeUser({ email: 'back@example.com' }))

    renderProvider()

    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('user')).toHaveTextContent('back@example.com')
  })

  it('becomes "anonymous" when there is no valid session', async () => {
    api.refreshSession.mockRejectedValue(new Error('401'))

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(api.getCurrentUser).not.toHaveBeenCalled()
  })

  it('login stores the user', async () => {
    api.refreshSession.mockRejectedValue(new Error('401'))
    api.login.mockResolvedValue()
    api.getCurrentUser.mockResolvedValue(makeUser({ email: 'a@example.com' }))
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))

    await userEvent.setup().click(screen.getByRole('button', { name: 'login' }))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(api.login).toHaveBeenCalledWith({ email: 'a@example.com', password: 'pw' })
    expect(screen.getByTestId('user')).toHaveTextContent('a@example.com')
  })

  it('logout clears the user even if the server cannot be reached', async () => {
    api.refreshSession.mockResolvedValue()
    api.getCurrentUser.mockResolvedValue(makeUser())
    api.logout.mockRejectedValue(new Error('network down'))
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    await userEvent.setup().click(screen.getByRole('button', { name: 'logout' }))

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')
  })

  it('logs out locally when the API client reports that the session expired', async () => {
    api.refreshSession.mockResolvedValue()
    api.getCurrentUser.mockResolvedValue(makeUser())
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    const handler = vi.mocked(setAuthFailureHandler).mock.calls.at(-1)?.[0]
    expect(handler).toBeTypeOf('function')
    act(() => handler?.())

    expect(screen.getByTestId('status')).toHaveTextContent('anonymous')
  })

  it('useAuth outside the provider throws a clear error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Probe />)).toThrow('useAuth must be used inside <AuthProvider>')
    spy.mockRestore()
  })
})
