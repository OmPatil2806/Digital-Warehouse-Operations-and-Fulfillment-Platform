/**
 * A small in-memory stand-in for the backend, plugged into the app's Axios clients.
 *
 * It knows four accounts, issues access tokens on login, keeps a "refresh cookie"
 * (so a page reload can restore the session), and can expire both to simulate a
 * session that ran out. Data endpoints answer with empty lists or the dashboard
 * fixtures: the flows under test are about getting in, around and out of the app.
 */
import { AxiosError, AxiosHeaders, type AxiosAdapter, type AxiosResponse } from 'axios'

import { apiClient, refreshClient } from '../src/api/apiClient'
import { tokenStore } from '../src/api/tokenStore'
import type { Role, User } from '../src/types/auth'
import {
  makeFulfillment,
  makeInventory,
  makeOverview,
  makeSuppliers,
  makeWarehouse,
} from '../src/test/dashboardFixtures'
import { makeHealthResponse } from '../src/test/fixtures'

export const PASSWORD = 'Demo-pass-123'

const ACCOUNTS: Record<string, { name: string; roles: Role[] }> = {
  'admin@example.com': { name: 'Ada Admin', roles: ['admin'] },
  'manager@example.com': { name: 'Maya Manager', roles: ['manager'] },
  'staff@example.com': { name: 'Sam Staff', roles: ['staff'] },
  'customer@example.com': { name: 'Chris Customer', roles: ['customer'] },
}

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 50 }

function user(email: string, id: number): User {
  return {
    id,
    email,
    full_name: ACCOUNTS[email].name,
    is_active: true,
    roles: ACCOUNTS[email].roles,
    last_login_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

export interface FakeBackend {
  /** Requests received, as "METHOD /path". */
  requests: string[]
  /** Log in as someone in a previous visit: the refresh cookie is there. */
  rememberSession(email: string): void
  /** The session runs out: the access token and the refresh cookie stop working. */
  expireSession(): void
  /** Restore the real network adapters. */
  close(): void
}

export function startFakeBackend(): FakeBackend {
  const requests: string[] = []
  const tokens = new Map<string, string>() // access token -> email
  let cookie: string | null = null // email whose refresh cookie the browser holds
  let counter = 0

  const issue = (email: string) => {
    counter += 1
    const token = `token-${counter}`
    tokens.set(token, email)
    return { access_token: token, token_type: 'bearer', expires_in: 900 }
  }

  const answer = (
    method: string,
    path: string,
    body: unknown,
    auth?: string,
  ): [number, unknown] => {
    if (method === 'POST' && path === '/auth/login') {
      const { email, password } = JSON.parse(String(body ?? '{}')) as Record<string, string>
      if (!(email in ACCOUNTS) || password !== PASSWORD) {
        return [401, { detail: 'Incorrect email or password' }]
      }
      cookie = email
      return [200, issue(email)]
    }
    if (method === 'POST' && path === '/auth/refresh') {
      return cookie ? [200, issue(cookie)] : [401, { detail: 'Session expired' }]
    }
    if (method === 'POST' && path === '/auth/logout') {
      cookie = null
      return [204, null]
    }
    const email = auth ? tokens.get(auth.replace('Bearer ', '')) : undefined
    if (!email) return [401, { detail: 'Not authenticated' }]
    if (path === '/auth/me') return [200, user(email, Object.keys(ACCOUNTS).indexOf(email) + 1)]
    if (path === '/health') return [200, makeHealthResponse()]
    if (path === '/alerts/summary') return [200, { unresolved: 0 }]
    if (path === '/dashboards/overview') return [200, makeOverview()]
    if (path === '/dashboards/inventory') return [200, makeInventory()]
    if (path === '/dashboards/fulfillment') return [200, makeFulfillment()]
    if (path === '/dashboards/warehouse') return [200, makeWarehouse()]
    if (path === '/dashboards/suppliers') return [200, makeSuppliers()]
    if (path === '/ml/summary') return [200, { as_of: null }]
    if (path === '/categories' || path === '/warehouses') {
      return [200, path === '/warehouses' ? [] : EMPTY_PAGE]
    }
    return [200, EMPTY_PAGE]
  }

  const adapter: AxiosAdapter = async (config) => {
    const method = (config.method ?? 'get').toUpperCase()
    const path = (config.url ?? '').replace(/^https?:\/\/[^/]+\/api\/v1/, '').split('?')[0]
    requests.push(`${method} ${path}`)
    const auth = config.headers?.get?.('Authorization') as string | undefined
    const [status, data] = answer(method, path, config.data, auth)
    const response: AxiosResponse = {
      data,
      status,
      statusText: String(status),
      headers: new AxiosHeaders(),
      config,
    }
    if (status < 300) return response
    throw new AxiosError(`HTTP ${status}`, 'ERR_BAD_RESPONSE', config, null, response)
  }

  const originals = [apiClient.defaults.adapter, refreshClient.defaults.adapter]
  apiClient.defaults.adapter = adapter
  refreshClient.defaults.adapter = adapter
  tokenStore.clear()

  return {
    requests,
    rememberSession(email) {
      cookie = email
    },
    expireSession() {
      tokens.clear()
      cookie = null
    },
    close() {
      ;[apiClient.defaults.adapter, refreshClient.defaults.adapter] = originals
      tokenStore.clear()
    },
  }
}
