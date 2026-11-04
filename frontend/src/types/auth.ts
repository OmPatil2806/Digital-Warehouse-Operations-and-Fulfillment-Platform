/** The four platform roles (mirrors backend RoleName). */
export const ROLES = ['admin', 'manager', 'staff', 'customer'] as const
export type Role = (typeof ROLES)[number]

/** A user as returned by GET /auth/me and /users (mirrors backend UserResponse). */
export interface User {
  id: number
  email: string
  full_name: string
  is_active: boolean
  roles: Role[]
  last_login_at: string | null
  created_at: string
  updated_at: string
}

/** Body of POST /auth/login. */
export interface LoginCredentials {
  email: string
  password: string
}

/** Response of POST /auth/login and /auth/refresh (mirrors backend TokenResponse). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}
