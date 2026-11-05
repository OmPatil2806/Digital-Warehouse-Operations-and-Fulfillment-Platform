import { zodResolver } from '@hookform/resolvers/zod'
import { AlertCircle } from 'lucide-react'
import { useForm, type UseFormRegisterReturn } from 'react-hook-form'
import { z } from 'zod'

import { getErrorMessage } from '../../api/apiClient'
import { createUser, updateUser, userKeys } from '../../api/usersApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { ROLES, type User } from '../../types/auth'
import { Button } from '../common/Button'
import { Modal } from '../common/Modal'
import { TextField } from '../form/fields'
import { passwordSchema, ROLE_DESCRIPTIONS, rolesSchema } from './userSchemas'

function ServerError({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p
      role="alert"
      className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
    >
      <AlertCircle size={16} aria-hidden="true" />
      {message}
    </p>
  )
}

/** One checkbox per role; React Hook Form collects the checked values into an array. */
function RoleCheckboxes({
  registration,
  error,
}: {
  registration: UseFormRegisterReturn<'roles'>
  error?: string
}) {
  return (
    <fieldset aria-describedby={error ? 'roles-error' : undefined}>
      <legend className="text-sm font-medium text-slate-700">
        Roles{' '}
        <span className="text-red-600" aria-hidden="true">
          *
        </span>
      </legend>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {ROLES.map((role) => (
          <label
            key={role}
            className="flex items-start gap-2 rounded-lg border border-slate-200 p-2 text-sm"
          >
            <input type="checkbox" value={role} className="mt-0.5 h-4 w-4" {...registration} />
            <span>
              <span className="font-medium capitalize">{role}</span>
              <span className="block text-xs text-slate-500">{ROLE_DESCRIPTIONS[role]}</span>
            </span>
          </label>
        ))}
      </div>
      {error && (
        <p id="roles-error" className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
    </fieldset>
  )
}

// ------------------------------------------------------------------- create / edit
const baseSchema = z.object({
  email: z.email('Enter a valid email address'),
  full_name: z.string().trim().min(1, 'Name is required').max(120),
  roles: rolesSchema,
})
const createSchema = baseSchema.extend({ password: passwordSchema })
type CreateValues = z.infer<typeof createSchema>
type EditValues = z.infer<typeof baseSchema>

interface UserFormProps {
  open: boolean
  onClose: () => void
  /** Edit this user; create a new one when omitted. */
  user?: User
}

export function UserFormDialog({ open, ...props }: UserFormProps) {
  if (!open) return null
  return props.user ? (
    <EditUserForm key={props.user.id} {...props} user={props.user} />
  ) : (
    <CreateUserForm {...props} />
  )
}

function CreateUserForm({ onClose }: Omit<UserFormProps, 'open'>) {
  const { register, handleSubmit, setError, formState } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { email: '', full_name: '', password: '', roles: ['customer'] },
  })
  const create = useApiMutation(createUser, {
    invalidates: [userKeys.all],
    successMessage: (u) => `User ${u.email} created`,
    toastOnError: false,
    onSuccess: onClose,
  })
  const submit = (values: CreateValues) =>
    create.mutate(values, {
      onError: (error) => {
        if (/email already exists/i.test(getErrorMessage(error))) {
          setError('email', { message: getErrorMessage(error) })
        }
      },
    })
  const formError =
    create.errorMessage && !/email already exists/i.test(create.errorMessage)
      ? create.errorMessage
      : null

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!create.isPending}
      title="New user"
      description="Share the password with the person securely; they can use it right away."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="user-form" loading={create.isPending}>
            Create user
          </Button>
        </>
      }
    >
      <form id="user-form" noValidate onSubmit={handleSubmit(submit)} className="space-y-4">
        <ServerError message={formError} />
        <TextField
          label="Email"
          type="email"
          required
          error={formState.errors.email?.message}
          {...register('email')}
        />
        <TextField
          label="Full name"
          required
          error={formState.errors.full_name?.message}
          {...register('full_name')}
        />
        <TextField
          label="Initial password"
          type="password"
          autoComplete="new-password"
          required
          hint="At least 8 characters with a letter and a digit"
          error={formState.errors.password?.message}
          {...register('password')}
        />
        <RoleCheckboxes registration={register('roles')} error={formState.errors.roles?.message} />
      </form>
    </Modal>
  )
}

function EditUserForm({ onClose, user }: Omit<UserFormProps, 'open'> & { user: User }) {
  const { register, handleSubmit, setError, formState } = useForm<EditValues>({
    resolver: zodResolver(baseSchema),
    defaultValues: { email: user.email, full_name: user.full_name, roles: user.roles },
  })
  const save = useApiMutation((values: EditValues) => updateUser(user.id, values), {
    invalidates: [userKeys.all],
    successMessage: (u) => `${u.email} updated`,
    toastOnError: false,
    onSuccess: onClose,
  })
  const submit = (values: EditValues) =>
    save.mutate(values, {
      onError: (error) => {
        if (/email already exists/i.test(getErrorMessage(error))) {
          setError('email', { message: getErrorMessage(error) })
        }
      },
    })
  const formError =
    save.errorMessage && !/email already exists/i.test(save.errorMessage) ? save.errorMessage : null

  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!save.isPending}
      title={`Edit ${user.full_name}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="user-form" loading={save.isPending}>
            Save changes
          </Button>
        </>
      }
    >
      <form id="user-form" noValidate onSubmit={handleSubmit(submit)} className="space-y-4">
        <ServerError message={formError} />
        <TextField
          label="Email"
          type="email"
          required
          error={formState.errors.email?.message}
          {...register('email')}
        />
        <TextField
          label="Full name"
          required
          error={formState.errors.full_name?.message}
          {...register('full_name')}
        />
        <RoleCheckboxes registration={register('roles')} error={formState.errors.roles?.message} />
      </form>
    </Modal>
  )
}

// ------------------------------------------------------------------ reset password
const resetSchema = z
  .object({ password: passwordSchema, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ['confirm'], message: 'Passwords do not match' })
type ResetValues = z.infer<typeof resetSchema>

export function ResetPasswordDialog({ user, onClose }: { user: User | null; onClose: () => void }) {
  return user ? <ResetPasswordForm key={user.id} user={user} onClose={onClose} /> : null
}

function ResetPasswordForm({ user, onClose }: { user: User; onClose: () => void }) {
  const { register, handleSubmit, formState } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { password: '', confirm: '' },
  })
  const reset = useApiMutation((v: ResetValues) => updateUser(user.id, { password: v.password }), {
    invalidates: [userKeys.all],
    successMessage: `Password changed — ${user.email} has been signed out everywhere`,
    toastOnError: false,
    onSuccess: onClose,
  })
  return (
    <Modal
      open
      onClose={onClose}
      dismissible={!reset.isPending}
      title={`Reset password for ${user.full_name}`}
      description="All of this user's sessions end immediately; they sign in again with the new password."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={reset.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="reset-form" loading={reset.isPending}>
            Set new password
          </Button>
        </>
      }
    >
      <form
        id="reset-form"
        noValidate
        onSubmit={handleSubmit((v) => reset.mutate(v))}
        className="space-y-4"
      >
        <ServerError message={reset.errorMessage} />
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          hint="At least 8 characters with a letter and a digit"
          error={formState.errors.password?.message}
          {...register('password')}
        />
        <TextField
          label="Repeat new password"
          type="password"
          autoComplete="new-password"
          error={formState.errors.confirm?.message}
          {...register('confirm')}
        />
      </form>
    </Modal>
  )
}
