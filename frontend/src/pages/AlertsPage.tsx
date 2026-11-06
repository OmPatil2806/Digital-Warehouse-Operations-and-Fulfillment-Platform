import { Check, Eye } from 'lucide-react'
import { Link } from 'react-router'

import { acknowledgeAlert, alertKeys, listAlerts, resolveAlert } from '../api/alertsApi'
import { Badge, type BadgeTone } from '../components/common/Badge'
import { Button } from '../components/common/Button'
import { DataTable, type Column } from '../components/common/DataTable'
import { FilterSelect, PageHeader } from '../components/common/PageHeader'
import { formatDateTime } from '../components/inventory/movementFormat'
import { isApprover } from '../components/inventory/operations'
import { useApiMutation } from '../hooks/useApiMutation'
import { useApiQuery } from '../hooks/useApiQuery'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'
import {
  ALERT_TYPES,
  type Alert,
  type AlertSeverity,
  type AlertStatus,
  type AlertType,
} from '../types/alerts'

const PAGE_SIZE = 25
const URL_DEFAULTS = { status: 'unresolved', type: '', offset: '0' }

const TYPE_LABELS: Record<AlertType, string> = {
  low_stock: 'Low stock',
  over_capacity: 'Bin over capacity',
  predicted_stockout: 'Predicted stockout',
  delay_risk: 'Delay risk',
  overdue_supplier: 'Overdue supplier',
}
const SEVERITY_TONES: Record<AlertSeverity, BadgeTone> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
}
const STATUS_TONES: Record<AlertStatus, BadgeTone> = {
  open: 'danger',
  acknowledged: 'info',
  resolved: 'success',
}

function statusText(alert: Alert): string {
  if (alert.status === 'acknowledged' && alert.acknowledged_by)
    return `Acknowledged by ${alert.acknowledged_by.full_name}`
  if (alert.status === 'resolved')
    return alert.resolved_by
      ? `Resolved by ${alert.resolved_by.full_name}`
      : 'Resolved automatically'
  return 'Open'
}

/** Low-stock and over-capacity alerts; they open and close themselves with the stock. */
export default function AlertsPage() {
  const { user } = useAuth()
  const canHandle = isApprover(user)
  const [filters, setFilters] = useUrlState(URL_DEFAULTS)

  const params = {
    status: (filters.status || undefined) as AlertStatus | 'unresolved' | undefined,
    alertType: (filters.type || undefined) as AlertType | undefined,
    offset: Number(filters.offset),
    limit: PAGE_SIZE,
  }
  const alerts = useApiQuery(alertKeys.list(params), () => listAlerts(params), {
    keepPrevious: true,
  })

  const act = useApiMutation(
    ({ alert, action }: { alert: Alert; action: 'acknowledge' | 'resolve' }) =>
      action === 'acknowledge' ? acknowledgeAlert(alert.id) : resolveAlert(alert.id),
    {
      invalidates: [alertKeys.all],
      successMessage: (a) => `${a.title}: ${a.status}`,
    },
  )

  const columns: Column<Alert>[] = [
    {
      key: 'severity',
      header: 'Severity',
      cell: (a) => <Badge tone={SEVERITY_TONES[a.severity]}>{a.severity}</Badge>,
    },
    {
      key: 'alert',
      header: 'Alert',
      cell: (a) => (
        <div>
          <p className="font-medium">{a.title}</p>
          {a.message && <p className="text-xs text-slate-500">{a.message}</p>}
          <p className="mt-1 text-xs text-slate-400">{TYPE_LABELS[a.alert_type]}</p>
        </div>
      ),
    },
    {
      key: 'about',
      header: 'About',
      cell: (a) =>
        a.product ? (
          <Link
            to={`/inventory?product=${a.product.id}`}
            className="font-mono text-xs whitespace-nowrap text-blue-700 hover:underline"
          >
            {a.product.sku}
          </Link>
        ) : a.bin ? (
          <span className="font-mono text-xs whitespace-nowrap">{a.bin.location_code}</span>
        ) : (
          '—'
        ),
    },
    {
      key: 'raised',
      header: 'Raised',
      cell: (a) => (
        <div className="text-xs whitespace-nowrap">
          <p>{formatDateTime(a.created_at)}</p>
          {a.updated_at !== a.created_at && a.status !== 'resolved' && (
            <p className="text-slate-500">updated {formatDateTime(a.updated_at)}</p>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (a) => (
        <div>
          <Badge tone={STATUS_TONES[a.status]}>{a.status}</Badge>
          <p className="mt-1 text-xs text-slate-500">{statusText(a)}</p>
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      cell: (a) =>
        canHandle &&
        a.status !== 'resolved' && (
          <div className="flex justify-end gap-1">
            {a.status === 'open' && (
              <Button
                size="sm"
                variant="secondary"
                icon={<Eye size={14} aria-hidden="true" />}
                aria-label={`Acknowledge ${a.title}`}
                onClick={() => act.mutate({ alert: a, action: 'acknowledge' })}
              >
                Acknowledge
              </Button>
            )}
            <Button
              size="sm"
              variant="secondary"
              icon={<Check size={14} aria-hidden="true" />}
              aria-label={`Resolve ${a.title}`}
              onClick={() => act.mutate({ alert: a, action: 'resolve' })}
            >
              Resolve
            </Button>
          </div>
        ),
    },
  ]

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Alerts"
        description="Raised and resolved automatically after every stock change. Acknowledge an alert when someone is on it."
      />
      <div className="flex flex-wrap items-center gap-3">
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ status })}
          options={[
            { value: 'unresolved', label: 'Needs attention' },
            { value: 'open', label: 'Open' },
            { value: 'acknowledged', label: 'Acknowledged' },
            { value: 'resolved', label: 'Resolved' },
            { value: '', label: 'All' },
          ]}
        />
        <FilterSelect
          label="Type"
          value={filters.type}
          onChange={(type) => setFilters({ type })}
          options={[
            { value: '', label: 'All types' },
            ...ALERT_TYPES.map((t) => ({ value: t, label: TYPE_LABELS[t] })),
          ]}
        />
      </div>
      <DataTable
        caption="Alerts"
        columns={columns}
        rows={alerts.data?.items}
        rowKey={(a) => a.id}
        isLoading={alerts.isPending}
        isRefreshing={alerts.isPlaceholderData}
        errorMessage={alerts.errorMessage}
        onRetry={() => void alerts.refetch()}
        emptyMessage={
          filters.status === 'unresolved' ? 'Nothing needs attention.' : 'No alerts match.'
        }
        pagination={
          alerts.data && {
            offset: alerts.data.offset,
            limit: alerts.data.limit,
            total: alerts.data.total,
            onChange: (offset) => setFilters({ offset: String(offset) }),
          }
        }
      />
    </div>
  )
}
