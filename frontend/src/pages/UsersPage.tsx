import { KeyRound, Pencil, Plus, UserCheck, UserX } from 'lucide-react'
import { useState } from 'react'

import { deactivateUser, listUsers, updateUser, userKeys } from '../api/usersApi'
import { Badge, StatusBadge } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { ConfirmDialog } from '../components/common/ConfirmDialog'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { SearchInput } from '../components/common/SearchInput'
import { ResetPasswordDialog, UserFormDialog } from '../components/users/UserDialogs'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import { ROLES, type Role, type User } from '../types/auth'
import type { ActiveFilter } from '../types/catalog'

const PAGE_SIZE = 25
const URL_DEFAULTS = { q: '', role: '', status: 'all', offset: '0' }

const ROLE_TONES = {
  admin: 'danger',
  manager: 'info',
  staff: 'success',
  customer: 'warning',
} as const

function formatLastLogin(value: string | null): string {
  if (!value) return 'Never'
  return new Date(value).toLocaleString('en-IE', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Admin-only user management (create, edit roles, reset password, (de)activate). */
export default function UsersPage() {
  const { user: me } = useAuth()
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [resetting, setResetting] = useState<User | null>(null)
  const [toggling, setToggling] = useState<User | null>(null)

  const params = {
    q: filters.q || undefined,
    role: (filters.role || undefined) as Role | undefined,
    status: filters.status as ActiveFilter,
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const users = useApiQuery([...userKeys.all, params], () => listUsers(params), {
    keepPrevious: true,
  })

  const toggle = useApiMutation(
    (user: User) =>
      user.is_active ? deactivateUser(user.id) : updateUser(user.id, { is_active: true }),
    {
      invalidates: [userKeys.all],
      successMessage: (u) =>
        `${u.email} ${u.is_active ? 'reactivated' : 'deactivated — all sessions ended'}`,
      onSuccess: () => setToggling(null),
      // Safety-rule messages from the backend (e.g. last admin) are shown as an error toast.
    },
  )

  const columns: Column<User>[] = [
    {
      key: 'name',
      header: 'User',
      cell: (u) => (
        <div>
          <p className="font-medium">
            {u.full_name}
            {u.id === me?.id && (
              <span className="ml-2">
                <Badge tone="neutral">You</Badge>
              </span>
            )}
          </p>
          <p className="text-xs text-slate-500">{u.email}</p>
        </div>
      ),
    },
    {
      key: 'roles',
      header: 'Roles',
      cell: (u) => (
        <div className="flex flex-wrap gap-1">
          {u.roles.map((role) => (
            <Badge key={role} tone={ROLE_TONES[role]}>
              {role}
            </Badge>
          ))}
        </div>
      ),
    },
    { key: 'status', header: 'Status', cell: (u) => <StatusBadge active={u.is_active} /> },
    { key: 'last_login', header: 'Last login', cell: (u) => formatLastLogin(u.last_login_at) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (u) => (
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Edit ${u.email}`}
            icon={<Pencil size={14} aria-hidden="true" />}
            onClick={() => setEditing(u)}
          />
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Reset password for ${u.email}`}
            icon={<KeyRound size={14} aria-hidden="true" />}
            onClick={() => setResetting(u)}
          />
          {u.id !== me?.id && (
            <Button
              variant="ghost"
              size="sm"
              aria-label={`${u.is_active ? 'Deactivate' : 'Reactivate'} ${u.email}`}
              icon={
                u.is_active ? (
                  <UserX size={14} aria-hidden="true" />
                ) : (
                  <UserCheck size={14} aria-hidden="true" />
                )
              }
              onClick={() => setToggling(u)}
            />
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Users"
        description="Accounts and roles. Only administrators can see this page."
        actions={
          <Button icon={<Plus size={16} aria-hidden="true" />} onClick={() => setCreating(true)}>
            New user
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          label="Search users"
          placeholder="Name or email"
          value={filters.q}
          onChange={(q) => setFilters({ q })}
        />
        <FilterSelect
          label="Role"
          value={filters.role}
          onChange={(role) => setFilters({ role })}
          options={[
            { value: '', label: 'All roles' },
            ...ROLES.map((r) => ({ value: r, label: r[0].toUpperCase() + r.slice(1) })),
          ]}
        />
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: 'all', label: 'All' },
            { value: 'active', label: 'Active' },
            { value: 'archived', label: 'Deactivated' },
          ]}
        />
      </div>

      <DataTable
        caption="Users"
        columns={columns}
        rows={users.data?.items}
        rowKey={(u) => u.id}
        isLoading={users.isPending}
        isRefreshing={users.isPlaceholderData}
        errorMessage={users.errorMessage}
        onRetry={() => void users.refetch()}
        emptyMessage="No users match your filters."
        pagination={
          users.data && {
            offset: users.data.offset,
            limit: users.data.limit,
            total: users.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />

      <UserFormDialog open={creating} onClose={() => setCreating(false)} />
      <UserFormDialog
        open={editing !== null}
        user={editing ?? undefined}
        onClose={() => setEditing(null)}
      />
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      <ConfirmDialog
        open={toggling !== null}
        title={
          toggling?.is_active
            ? `Deactivate ${toggling.email}?`
            : `Reactivate ${toggling?.email ?? ''}?`
        }
        message={
          toggling?.is_active
            ? 'The user can no longer sign in and all of their sessions end immediately. You can reactivate them later.'
            : 'The user can sign in again with their existing password.'
        }
        confirmLabel={toggling?.is_active ? 'Deactivate' : 'Reactivate'}
        tone={toggling?.is_active ? 'danger' : 'primary'}
        loading={toggle.isPending}
        onConfirm={() => toggling && toggle.mutate(toggling)}
        onCancel={() => setToggling(null)}
      />
    </div>
  )
}
