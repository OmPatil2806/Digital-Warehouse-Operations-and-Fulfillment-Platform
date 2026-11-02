import type { HealthResponse } from '../types/health'
import { apiClient } from './apiClient'

/** Fetch the backend health status. */
export async function getHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>('/health')
  return data
}
