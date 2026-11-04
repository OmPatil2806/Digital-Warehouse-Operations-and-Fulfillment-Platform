import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { describe, expect, it, vi } from 'vitest'

import { loggedInAs, makeAuth, renderWithAuth } from '../test/renderWithAuth'
import LoginPage from './LoginPage'

const routes = {
  '/': <p>dashboard page</p>,
  '/orders': <p>orders page</p>,
}

function renderLogin(options: Parameters<typeof renderWithAuth>[1] = {}) {
  const auth = options.auth ?? makeAuth()
  renderWithAuth(<LoginPage />, { path: '/login', routes, ...options, auth })
  return { auth, user: userEvent.setup() }
}

function apiError(status: number, detail: string): AxiosError {
  const response = {
    status,
    data: { detail },
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, response)
}

describe('LoginPage', () => {
  it('shows required-field errors and does not call login', async () => {
    const { auth, user } = renderLogin()

    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Email is required')).toBeInTheDocument()
    expect(screen.getByText('Password is required')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(auth.login).not.toHaveBeenCalled()
  })

  it('rejects an invalid email address', async () => {
    const { auth, user } = renderLogin()

    await user.type(screen.getByLabelText('Email'), 'not-an-email')
    await user.type(screen.getByLabelText('Password'), 'whatever')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(auth.login).not.toHaveBeenCalled()
  })

  it('logs in with trimmed email and goes to the dashboard', async () => {
    const { auth, user } = renderLogin()

    await user.type(screen.getByLabelText('Email'), '  admin@example.com ')
    await user.type(screen.getByLabelText('Password'), 'Passw0rd-123')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('dashboard page')).toBeInTheDocument()
    expect(auth.login).toHaveBeenCalledWith({
      email: 'admin@example.com',
      password: 'Passw0rd-123',
    })
  })

  it('returns to the page the user originally asked for', async () => {
    const { user } = renderLogin({ state: { from: { pathname: '/orders', search: '', hash: '' } } })

    await user.type(screen.getByLabelText('Email'), 'staff@example.com')
    await user.type(screen.getByLabelText('Password'), 'Passw0rd-123')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('orders page')).toBeInTheDocument()
  })

  it('shows the server error message and stays on the page', async () => {
    const auth = makeAuth({
      login: vi.fn().mockRejectedValue(apiError(401, 'Incorrect email or password')),
    })
    const { user } = renderLogin({ auth })

    await user.type(screen.getByLabelText('Email'), 'admin@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password')
    expect(screen.queryByText('dashboard page')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
  })

  it('disables the button and shows progress while signing in', async () => {
    let finishLogin: () => void = () => {}
    const auth = makeAuth({
      login: vi.fn(() => new Promise<void>((resolve) => (finishLogin = resolve))),
    })
    const { user } = renderLogin({ auth })

    await user.type(screen.getByLabelText('Email'), 'admin@example.com')
    await user.type(screen.getByLabelText('Password'), 'Passw0rd-123')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    const button = await screen.findByRole('button', { name: 'Signing in…' })
    expect(button).toBeDisabled()
    finishLogin()
    await waitFor(() => expect(screen.getByText('dashboard page')).toBeInTheDocument())
  })

  it('toggles password visibility', async () => {
    const { user } = renderLogin()
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')

    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(password).toHaveAttribute('type', 'text')

    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(password).toHaveAttribute('type', 'password')
  })

  it('redirects users who are already logged in', () => {
    renderLogin({ auth: loggedInAs('staff') })

    expect(screen.getByText('dashboard page')).toBeInTheDocument()
  })
})
