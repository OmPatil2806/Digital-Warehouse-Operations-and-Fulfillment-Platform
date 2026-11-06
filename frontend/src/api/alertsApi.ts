import type { Alert, AlertStatus, AlertType, AuditLogEntry } from '../types/alerts'
import type { Page } from '../types/catalog'
import { apiClient } from './apiClient'

export const alertKeys = {
  all: ['alerts'] as const,
  list: (params: object) => ['alerts', 'list', params] as const,
  summary: ['alerts', 'summary'] as const,
}

export const auditKeys = {
  list: (params: object) => ['audit-logs', params] as const,
}

export interface AlertListParams {
  /** "unresolved" = open and acknowledged. */
  status?: AlertStatus | 'unresolved'
  alertType?: AlertType
  offset?: number
  limit?: number
}

export async function listAlerts(params: AlertListParams = {}): Promise<Page<Alert>> {
  const unresolved = params.status === 'unresolved'
  const { data } = await apiClient.get<Page<Alert>>('/alerts', {
    params: {
      unresolved: unresolved || undefined,
      status: unresolved ? undefined : params.status,
      alert_type: params.alertType,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}

export async function getAlertSummary(): Promise<{ unresolved: number }> {
  const { data } = await apiClient.get<{ unresolved: number }>('/alerts/summary')
  return data
}

export async function acknowledgeAlert(id: number): Promise<Alert> {
  const { data } = await apiClient.post<Alert>(`/alerts/${id}/acknowledge`)
  return data
}

export async function resolveAlert(id: number): Promise<Alert> {
  const { data } = await apiClient.post<Alert>(`/alerts/${id}/resolve`)
  return data
}

export interface AuditListParams {
  entityType?: string
  entityId?: number
  action?: string
  offset?: number
  limit?: number
}

export async function listAuditLogs(params: AuditListParams = {}): Promise<Page<AuditLogEntry>> {
  const { data } = await apiClient.get<Page<AuditLogEntry>>('/audit-logs', {
    params: {
      entity_type: params.entityType,
      entity_id: params.entityId,
      action: params.action,
      offset: params.offset,
      limit: params.limit,
    },
  })
  return data
}
