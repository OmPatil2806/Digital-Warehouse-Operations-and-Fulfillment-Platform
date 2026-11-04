import {
  AxiosError,
  AxiosHeaders,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { apiClient, refreshAccessToken, refreshClient, setAuthFailureHandler } from './apiClient'
import { tokenStore } from './tokenStore'

/**
 * A fake network layer: every request is answered by `handler` instead of the backend.
 * `handler` returns [status, body].
 */
type Handler = (
  config: InternalAxiosRequestConfig,
) => [number, unknown] | Promise<[number, unknown]>

function fakeAdapter(handler: Handler): AxiosAdapter {
  return async (config) => {
    const [status, data] = await handler(config)
    const response: AxiosResponse = {
      data,
      status,
      statusText: String(status),
      headers: new AxiosHeaders(),
      config,
    }
    if (status >= 200 && status < 300) return response
    throw new AxiosError(`HTTP ${status}`, 'ERR_BAD_RESPONSE', config, null, response)
  }
}

const authHeader = (config: InternalAxiosRequestConfig) =>
  config.headers.get('Authorization') as string | undefined

const originalApiAdapter = apiClient.defaults.adapter
const originalRefreshAdapter = refreshClient.defaults.adapter

/** API that accepts only the "fresh" token. */
const protectedApi: Handler = (config) =>
  authHeader(config) === 'Bearer fresh' ? [200, { ok: true }] : [401, { detail: 'expired' }]

let refreshCalls: number
let failureHandler: Mock<() => void>

beforeEach(() => {
  tokenStore.clear()
  refreshCalls = 0
  failureHandler = vi.fn<() => void>()
  setAuthFailureHandler(failureHandler)
})

afterEach(() => {
  apiClient.defaults.adapter = originalApiAdapter
  refreshClient.defaults.adapter = originalRefreshAdapter
  setAuthFailureHandler(null)
  tokenStore.clear()
})

function refreshSucceeds(delayMs = 0) {
  refreshClient.defaults.adapter = fakeAdapter(async () => {
    refreshCalls += 1
    await new Promise((resolve) => setTimeout(resolve, delayMs))
    return [200, { access_token: 'fresh', token_type: 'bearer', expires_in: 1800 }]
  })
}

function refreshFails() {
  refreshClient.defaults.adapter = fakeAdapter(() => {
    refreshCalls += 1
    return [401, { detail: 'Refresh token missing' }]
  })
}

describe('apiClient authentication', () => {
  it('sends the refresh cookie on cross-origin requests', () => {
    expect(apiClient.defaults.withCredentials).toBe(true)
    expect(refreshClient.defaults.withCredentials).toBe(true)
  })

  it('attaches the access token from memory', async () => {
    const seen: Array<string | undefined> = []
    apiClient.defaults.adapter = fakeAdapter((config) => {
      seen.push(authHeader(config))
      return [200, {}]
    })

    await apiClient.get('/anything')
    tokenStore.set('abc')
    await apiClient.get('/anything')

    expect(seen).toEqual([undefined, 'Bearer abc'])
  })

  it('on 401 refreshes the token once and retries the request', async () => {
    tokenStore.set('stale')
    apiClient.defaults.adapter = fakeAdapter(protectedApi)
    refreshSucceeds()

    const response = await apiClient.get('/inventory')

    expect(response.data).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
    expect(tokenStore.get()).toBe('fresh')
    expect(failureHandler).not.toHaveBeenCalled()
  })

  it('shares ONE refresh between many requests that fail at the same time', async () => {
    tokenStore.set('stale')
    apiClient.defaults.adapter = fakeAdapter(protectedApi)
    refreshSucceeds(20) // slow refresh, so all requests are waiting for it

    const results = await Promise.all([
      apiClient.get('/a'),
      apiClient.get('/b'),
      apiClient.get('/c'),
      apiClient.get('/d'),
    ])

    expect(results.map((r) => r.status)).toEqual([200, 200, 200, 200])
    expect(refreshCalls).toBe(1) // a second refresh would look like token theft
  })

  it('when refresh fails: clears the token, notifies the app and rejects with the 401', async () => {
    tokenStore.set('stale')
    apiClient.defaults.adapter = fakeAdapter(protectedApi)
    refreshFails()

    const error = await apiClient.get('/orders').catch((err: unknown) => err)

    expect(error).toBeInstanceOf(AxiosError)
    expect((error as AxiosError).response?.status).toBe(401)
    expect(tokenStore.get()).toBeNull()
    expect(failureHandler).toHaveBeenCalledOnce()
  })

  it('does not retry forever if the retried request is still 401', async () => {
    let calls = 0
    apiClient.defaults.adapter = fakeAdapter(() => {
      calls += 1
      return [401, { detail: 'still no' }]
    })
    refreshSucceeds()

    await expect(apiClient.get('/x')).rejects.toBeInstanceOf(AxiosError)
    expect(calls).toBe(2) // original + one retry
    expect(refreshCalls).toBe(1)
  })

  it.each(['/auth/login', '/auth/logout', '/auth/refresh'])(
    'never tries to refresh for %s',
    async (url) => {
      apiClient.defaults.adapter = fakeAdapter(() => [401, { detail: 'nope' }])
      refreshSucceeds()

      await expect(apiClient.post(url)).rejects.toBeInstanceOf(AxiosError)
      expect(refreshCalls).toBe(0)
    },
  )

  it('does not refresh on other errors such as 403 or 500', async () => {
    tokenStore.set('valid')
    apiClient.defaults.adapter = fakeAdapter((config) =>
      config.url === '/forbidden' ? [403, {}] : [500, {}],
    )
    refreshSucceeds()

    await expect(apiClient.get('/forbidden')).rejects.toBeInstanceOf(AxiosError)
    await expect(apiClient.get('/broken')).rejects.toBeInstanceOf(AxiosError)
    expect(refreshCalls).toBe(0)
  })

  it('refreshAccessToken can be called again after a previous refresh finished', async () => {
    refreshSucceeds()

    await refreshAccessToken()
    await refreshAccessToken()

    expect(refreshCalls).toBe(2)
  })
})
