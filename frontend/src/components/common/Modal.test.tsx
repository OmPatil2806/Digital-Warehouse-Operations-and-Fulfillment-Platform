import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ConfirmDialog } from './ConfirmDialog'
import { Modal } from './Modal'

function ModalHarness({ dismissible = true }: { dismissible?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Edit product"
        description="Change the product details."
        dismissible={dismissible}
        footer={<button>Save</button>}
      >
        <input aria-label="Name" />
      </Modal>
    </>
  )
}

describe('Modal', () => {
  it('opens with an accessible name and description', async () => {
    render(<ModalHarness />)

    await userEvent.setup().click(screen.getByRole('button', { name: 'Open' }))

    const dialog = screen.getByRole('dialog', { name: 'Edit product' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleDescription('Change the product details.')
  })

  it('moves focus inside, traps Tab, closes on Esc and restores focus', async () => {
    const user = userEvent.setup()
    render(<ModalHarness />)
    const opener = screen.getByRole('button', { name: 'Open' })

    await user.click(opener)
    const close = screen.getByRole('button', { name: 'Close dialog' })
    expect(close).toHaveFocus() // first focusable element

    await user.tab()
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus() // wrapped around, focus stays in the dialog
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes when the backdrop is clicked', async () => {
    const user = userEvent.setup()
    render(<ModalHarness />)
    await user.click(screen.getByRole('button', { name: 'Open' }))

    await user.click(screen.getByTestId('modal-backdrop'))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('cannot be closed while not dismissible', async () => {
    const user = userEvent.setup()
    render(<ModalHarness dismissible={false} />)
    await user.click(screen.getByRole('button', { name: 'Open' }))

    await user.keyboard('{Escape}')
    await user.click(screen.getByTestId('modal-backdrop'))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Close dialog' })).not.toBeInTheDocument()
  })

  it('blocks page scrolling while open', async () => {
    const user = userEvent.setup()
    render(<ModalHarness />)
    await user.click(screen.getByRole('button', { name: 'Open' }))
    expect(document.body.style.overflow).toBe('hidden')

    await user.keyboard('{Escape}')
    expect(document.body.style.overflow).toBe('')
  })
})

describe('ConfirmDialog', () => {
  function renderConfirm(loading = false) {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Archive product?"
        message="LAP-001 will no longer be available."
        confirmLabel="Archive"
        tone="danger"
        loading={loading}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )
    return { onConfirm, onCancel, user: userEvent.setup() }
  }

  it('focuses Cancel first, so Enter never confirms by accident', async () => {
    const { onConfirm, onCancel, user } = renderConfirm()

    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('confirms with the confirm button', async () => {
    const { onConfirm, user } = renderConfirm()

    await user.click(screen.getByRole('button', { name: 'Archive' }))

    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('locks both buttons while the action runs', () => {
    renderConfirm(true)

    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Archive' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Archive' })).toHaveAttribute('aria-busy', 'true')
  })
})
