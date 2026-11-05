import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../api/healthApi'
import * as usersApi from '../api/usersApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { page } from '../test/catalogFixtures'
import { makeHealthResponse } from '../test/fixtures'
import { loggedInAs, makeAuth, makeUser, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import UsersPage from './UsersPage'

vi.mock('../api/usersApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/usersApi')>()),
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deactivateUser: vi.fn(),
}))
vi.mock('../api/healthApi', () => ({ getHealth: vi.fn() }))
const api = vi.mocked(usersApi)

function httpError(status: number, detail: string): AxiosError {
  const response = {
    status,
    data: { detail },
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('fail', 'ERR', undefined, undefined, response)
}

const ME = makeUser({ id: 1, email: 'admin@example.com', full_name: 'Ada Admin', roles: ['admin'] })
const MAYA = makeUser({
  id: 2,
  email: 'maya@example.com',
  full_name: 'Maya Manager',
  roles: ['manager'],
})
const SAM = makeUser({
  id: 3,
  email: 'sam@example.com',
  full_name: 'Sam Staff',
  roles: ['staff'],
  is_active: false,
  last_login_at: null,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.listUsers.mockResolvedValue(page([ME, MAYA, SAM]))
})

function renderPage(path = '/users') {
  renderWithAuth(<UsersPage />, {
    auth: makeAuth({ status: 'authenticated', user: ME }),
    path,
    route: '/users',
  })
  return userEvent.setup()
}

const row = (email: string) => screen.getByText(email).closest('tr') as HTMLElement
const location = () => screen.getByTestId('location').textContent

describe('UsersPage', () => {
  it('lists users with roles, status and last login; marks the current user', async () => {
    renderPage()

    await screen.findByText('maya@example.com')
    expect(within(row('admin@example.com')).getByText('You')).toBeInTheDocument()
    expect(within(row('maya@example.com')).getByText('manager')).toBeInTheDocument()
    expect(within(row('sam@example.com')).getByText('Archived')).toBeInTheDocument()
    expect(within(row('sam@example.com')).getByText('Never')).toBeInTheDocument()
  })

  it('offers no deactivate button for yourself', async () => {
    renderPage()

    await screen.findByText('maya@example.com')
    expect(
      screen.queryByRole('button', { name: 'Deactivate admin@example.com' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Deactivate maya@example.com' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reactivate sam@example.com' })).toBeInTheDocument()
  })

  it('filters by role and status via the URL', async () => {
    const user = renderPage('/users?role=staff&status=archived')

    await screen.findByText('maya@example.com')
    expect(api.listUsers).toHaveBeenLastCalledWith({
      q: undefined,
      role: 'staff',
      status: 'archived',
      offset: 0,
      limit: 25,
    })

    await user.selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'Manager')
    expect(location()).toBe('/users?role=manager&status=archived')
  })

  describe('creating a user', () => {
    async function openForm() {
      const user = renderPage()
      await user.click(await screen.findByRole('button', { name: 'New user' }))
      return { user, dialog: within(screen.getByRole('dialog', { name: 'New user' })) }
    }

    it('checks email, password policy and roles before sending', async () => {
      const { user, dialog } = await openForm()

      await user.type(dialog.getByRole('textbox', { name: /Email/ }), 'not-an-email')
      await user.type(dialog.getByLabelText(/Initial password/), 'onlyletters')
      await user.click(dialog.getByRole('checkbox', { name: /customer/i })) // untick the default
      await user.click(dialog.getByRole('button', { name: 'Create user' }))

      expect(await dialog.findByText('Enter a valid email address')).toBeInTheDocument()
      expect(dialog.getByText('Name is required')).toBeInTheDocument()
      expect(dialog.getByText('Must contain a digit')).toBeInTheDocument()
      expect(dialog.getByText('Choose at least one role')).toBeInTheDocument()
      expect(api.createUser).not.toHaveBeenCalled()
    })

    it('creates a user with several roles', async () => {
      api.createUser.mockResolvedValue(makeUser({ email: 'new@example.com' }))
      const { user, dialog } = await openForm()

      await user.type(dialog.getByRole('textbox', { name: /Email/ }), 'new@example.com')
      await user.type(dialog.getByRole('textbox', { name: /Full name/ }), 'New Person')
      await user.type(dialog.getByLabelText(/Initial password/), 'Welcome-123')
      await user.click(dialog.getByRole('checkbox', { name: /customer/i }))
      await user.click(dialog.getByRole('checkbox', { name: /staff/i }))
      await user.click(dialog.getByRole('checkbox', { name: /manager/i }))
      await user.click(dialog.getByRole('button', { name: 'Create user' }))

      await waitFor(() =>
        expect(api.createUser).toHaveBeenCalledWith(
          {
            email: 'new@example.com',
            full_name: 'New Person',
            password: 'Welcome-123',
            roles: expect.arrayContaining(['staff', 'manager']),
          },
          expect.anything(),
        ),
      )
      expect(api.createUser.mock.calls[0][0].roles).toHaveLength(2)
      expect(await screen.findByRole('status')).toHaveTextContent('User new@example.com created')
    })

    it('shows "email already exists" under the email field', async () => {
      api.createUser.mockRejectedValue(httpError(409, 'A user with this email already exists'))
      const { user, dialog } = await openForm()

      await user.type(dialog.getByRole('textbox', { name: /Email/ }), 'maya@example.com')
      await user.type(dialog.getByRole('textbox', { name: /Full name/ }), 'Maya Again')
      await user.type(dialog.getByLabelText(/Initial password/), 'Welcome-123')
      await user.click(dialog.getByRole('button', { name: 'Create user' }))

      await waitFor(() =>
        expect(dialog.getByRole('textbox', { name: /Email/ })).toHaveAccessibleDescription(
          'A user with this email already exists',
        ),
      )
    })
  })

  it('edits roles and shows safety-rule errors from the server', async () => {
    api.updateUser.mockRejectedValue(
      httpError(409, 'You cannot remove the admin role from your own account'),
    )
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Edit admin@example.com' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Edit Ada Admin' }))
    expect(dialog.getByRole('checkbox', { name: /admin/i })).toBeChecked()
    await user.click(dialog.getByRole('checkbox', { name: /admin/i }))
    await user.click(dialog.getByRole('checkbox', { name: /manager/i }))
    await user.click(dialog.getByRole('button', { name: 'Save changes' }))

    await waitFor(() =>
      expect(api.updateUser).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ roles: ['manager'] }),
      ),
    )
    expect(await dialog.findByRole('alert')).toHaveTextContent(
      'You cannot remove the admin role from your own account',
    )
  })

  it('resets a password (both entries must match)', async () => {
    api.updateUser.mockResolvedValue(MAYA)
    const user = renderPage()

    await user.click(
      await screen.findByRole('button', { name: 'Reset password for maya@example.com' }),
    )
    const dialog = within(screen.getByRole('dialog', { name: 'Reset password for Maya Manager' }))
    await user.type(dialog.getByLabelText('New password'), 'Brand-new-99')
    await user.type(dialog.getByLabelText('Repeat new password'), 'Brand-new-98')
    await user.click(dialog.getByRole('button', { name: 'Set new password' }))
    expect(await dialog.findByText('Passwords do not match')).toBeInTheDocument()

    await user.clear(dialog.getByLabelText('Repeat new password'))
    await user.type(dialog.getByLabelText('Repeat new password'), 'Brand-new-99')
    await user.click(dialog.getByRole('button', { name: 'Set new password' }))

    await waitFor(() =>
      expect(api.updateUser).toHaveBeenCalledWith(2, { password: 'Brand-new-99' }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent('signed out everywhere')
  })

  it('deactivates and reactivates after confirmation', async () => {
    api.deactivateUser.mockResolvedValue({ ...MAYA, is_active: false })
    api.updateUser.mockResolvedValue({ ...SAM, is_active: true })
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Deactivate maya@example.com' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(api.deactivateUser).toHaveBeenCalledWith(2))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Reactivate sam@example.com' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reactivate' }))
    await waitFor(() => expect(api.updateUser).toHaveBeenCalledWith(3, { is_active: true }))
  })

  it('shows a server refusal (e.g. last admin) as an error message', async () => {
    api.deactivateUser.mockRejectedValue(httpError(409, 'Cannot deactivate the last active admin'))
    const user = renderPage()

    await user.click(await screen.findByRole('button', { name: 'Deactivate maya@example.com' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Deactivate' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Cannot deactivate the last active admin',
    )
  })
})

describe('/users route', () => {
  it.each(['manager', 'staff', 'customer'] as const)('is forbidden for %s', async (role) => {
    vi.mocked(getHealth).mockResolvedValue(makeHealthResponse())
    render(
      <TestProviders>
        <AuthContext value={loggedInAs(role)}>
          <MemoryRouter initialEntries={['/users']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )

    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listUsers).not.toHaveBeenCalled()
  })
})
