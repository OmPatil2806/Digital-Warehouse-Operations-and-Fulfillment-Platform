import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { makeAuth, makeUser, renderWithAuth } from '../../test/renderWithAuth'
import { Topbar } from './Topbar'

function renderTopbar() {
  const auth = makeAuth({
    status: 'authenticated',
    user: makeUser({
      full_name: 'Om Dipak Patil',
      email: 'om@example.com',
      roles: ['admin', 'manager'],
    }),
  })
  const onMenuClick = vi.fn()
  renderWithAuth(<Topbar onMenuClick={onMenuClick} />, { auth })
  return { auth, onMenuClick, user: userEvent.setup() }
}

describe('Topbar', () => {
  it('shows the user name, email, initials and one badge per role', () => {
    renderTopbar()

    expect(screen.getByText('Om Dipak Patil')).toBeInTheDocument()
    expect(screen.getByText('om@example.com')).toBeInTheDocument()
    expect(screen.getByText('OD')).toBeInTheDocument()
    const badges = within(screen.getByRole('list', { name: 'Your roles' })).getAllByRole('listitem')
    expect(badges.map((badge) => badge.textContent)).toEqual(['admin', 'manager'])
  })

  it('logs out when "Log out" is clicked', async () => {
    const { auth, user } = renderTopbar()

    await user.click(screen.getByRole('button', { name: 'Log out' }))

    expect(auth.logout).toHaveBeenCalledOnce()
  })

  it('opens the mobile menu', async () => {
    const { onMenuClick, user } = renderTopbar()

    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))

    expect(onMenuClick).toHaveBeenCalledOnce()
  })
})
