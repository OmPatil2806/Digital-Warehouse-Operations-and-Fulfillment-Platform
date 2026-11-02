import { AxiosError, AxiosHeaders, type AxiosResponse } from 'axios'
import { describe, expect, it } from 'vitest'

import { API_BASE_URL, apiClient, getErrorMessage } from './apiClient'

function httpError(status: number, data: unknown): AxiosError {
  const response = {
    status,
    data,
    statusText: '',
    headers: {},
    config: { headers: new AxiosHeaders() },
  } as AxiosResponse
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', undefined, undefined, response)
}

describe('apiClient', () => {
  it('uses the configured API base URL', () => {
    expect(apiClient.defaults.baseURL).toBe(API_BASE_URL)
    expect(API_BASE_URL).toMatch(/\/api\/v1$/)
  })
})

describe('getErrorMessage', () => {
  it('returns the backend "detail" message when present', () => {
    expect(getErrorMessage(httpError(400, { detail: 'SKU already exists' }))).toBe(
      'SKU already exists',
    )
  })

  it('falls back to the HTTP status when there is no string detail', () => {
    expect(getErrorMessage(httpError(500, {}))).toBe('Request failed (500)')
  })

  it('reports timeouts', () => {
    expect(getErrorMessage(new AxiosError('timeout', 'ECONNABORTED'))).toBe('Request timed out')
  })

  it('reports network errors when there is no response', () => {
    expect(getErrorMessage(new AxiosError('Network Error', 'ERR_NETWORK'))).toBe(
      'Cannot reach the server',
    )
  })

  it('handles plain errors and unknown values', () => {
    expect(getErrorMessage(new Error('Boom'))).toBe('Boom')
    expect(getErrorMessage('something odd')).toBe('Unexpected error')
  })
})
