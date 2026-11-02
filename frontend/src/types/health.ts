/** Response of GET /api/v1/health (mirrors backend HealthResponse). */
export interface HealthResponse {
  status: 'ok' | 'degraded'
  app_name: string
  version: string
  environment: string
  database: 'ok' | 'unavailable'
  timestamp: string
}
