import type { HealthResponse } from '../types/health'

/** Build a health response for tests, overriding only the fields a test cares about. */
export function makeHealthResponse(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'ok',
    app_name: 'Digital Warehouse Operations and Fulfillment Platform',
    version: '0.1.0',
    environment: 'test',
    database: 'ok',
    timestamp: '2026-11-02T10:00:00Z',
    ...overrides,
  }
}
