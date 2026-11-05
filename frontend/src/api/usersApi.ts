import type { Role, User } from '../types/auth'
import type { ActiveFilter, Page } from '../types/catalog'
import { apiClient } from './apiClient'

export const userKeys = {
  all: ['users'] as const,
}

export interface UserListParams {
  q?: string
  role?: Role
  status?: ActiveFilter
  offset?: number
  limit?: number
}

export async function listUsers(params: UserListParams = {}): Promise<Page<User>> {
  const query: Record<string, unknown> = { offset: params.offset, limit: params.limit }
  if (params.q) query.q = params.q
  if (params.role) query.role = params.role
  if (params.status === 'active') query.is_active = true
  if (params.status === 'archived') query.is_active = false
  const { data } = await apiClient.get<Page<User>>('/users', { params: query })
  return data
}

export interface UserCreateInput {
  email: string
  full_name: string
  password: string
  roles: Role[]
}

export async function createUser(input: UserCreateInput): Promise<User> {
  const { data } = await apiClient.post<User>('/users', input)
  return data
}

export async function updateUser(
  id: number,
  changes: Partial<UserCreateInput> & { is_active?: boolean },
): Promise<User> {
  const { data } = await apiClient.patch<User>(`/users/${id}`, changes)
  return data
}

export async function deactivateUser(id: number): Promise<User> {
  const { data } = await apiClient.post<User>(`/users/${id}/deactivate`)
  return data
}
