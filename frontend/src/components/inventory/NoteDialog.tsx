import { useState } from 'react'

import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { TextAreaField } from '../form/fields'

interface NoteDialogProps {
  open: boolean
  title: string
  description?: string
  label: string
  confirmLabel: string
  loading?: boolean
  onConfirm: (note: string) => void
  onCancel: () => void
}

/** Ask for a short required note (e.g. why a request is rejected). */
export function NoteDialog(props: NoteDialogProps) {
  return props.open ? <NoteForm {...props} /> : null
}

function NoteForm({
  open,
  title,
  description,
  label,
  confirmLabel,
  loading = false,
  onConfirm,
  onCancel,
}: NoteDialogProps) {
  const [note, setNote] = useState('')
  const [error, setError] = useState<string>()

  const confirm = () => {
    if (note.trim().length < 3) {
      setError('Write at least 3 characters')
      return
    }
    onConfirm(note.trim())
  }

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      size="sm"
      dismissible={!loading}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button variant="danger" loading={loading} onClick={confirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <TextAreaField
        label={label}
        required
        value={note}
        maxLength={255}
        onChange={(event) => setNote(event.target.value)}
        error={error}
        data-autofocus
      />
    </Modal>
  )
}
