import { useState, type ReactNode } from 'react'

import {
  decideReorder,
  decideSlotting,
  getModels,
  getMovementSummary,
  listDelayRisks,
  listMovements,
  listReorderRecommendations,
  listSlottingRecommendations,
  mlKeys,
} from '../../api/mlApi'
import { useApiMutation } from '../../hooks/useApiMutation'
import { useApiQuery } from '../../hooks/useApiQuery'
import type {
  DecisionStatus,
  MovementClass,
  ReorderRecommendation,
  RiskLevel,
  SlottingRecommendation,
} from '../../types/ml'
import { formatNumber } from '../../utils/format'
import { PaginationBar } from '../common/DataTable'
import { FilterSelect } from '../common/PageHeader'
import { DelayRiskTable } from './DelayRiskTable'
import { ModelsTable } from './ModelsTable'
import { MovementMatrix } from './MovementMatrix'
import { ReorderTable } from './ReorderTable'
import { SlottingList } from './SlottingList'

const PAGE = 25

const STATUS_OPTIONS = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: '', label: 'All decisions' },
]
const RISK_OPTIONS = [
  { value: '', label: 'All risk levels' },
  { value: 'high', label: 'High risk' },
  { value: 'medium', label: 'Medium risk' },
  { value: 'low', label: 'Low risk' },
]

/** Shared frame: filters on the left, the list, paging, loading and error states. */
function Panel({
  filters,
  isLoading,
  errorMessage,
  total,
  offset,
  onPage,
  intro,
  children,
}: {
  filters?: ReactNode
  isLoading: boolean
  errorMessage: string | null
  total?: number
  offset?: number
  onPage?: (offset: number) => void
  intro: string
  children: ReactNode
}) {
  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-4">
      <p className="text-sm text-slate-600">{intro}</p>
      {filters && <div className="flex flex-wrap gap-2">{filters}</div>}
      {errorMessage ? (
        <p role="alert" className="py-6 text-center text-sm text-red-700">
          {errorMessage}
        </p>
      ) : isLoading ? (
        <div className="h-40 animate-pulse rounded-lg bg-slate-50" aria-label="Loading" />
      ) : (
        children
      )}
      {onPage && total !== undefined && offset !== undefined && !errorMessage && (
        <PaginationBar offset={offset} limit={PAGE} total={total} onChange={onPage} />
      )}
    </section>
  )
}

export function ModelsPanel() {
  const query = useApiQuery(mlKeys.models, getModels)
  return (
    <Panel
      intro="Every use case compares simple baselines with neural networks on the most recent period, which no model saw while training. A network is only used when it beats the baseline."
      isLoading={query.isLoading}
      errorMessage={query.errorMessage}
    >
      <ModelsTable models={query.data ?? []} />
    </Panel>
  )
}

export function ReorderPanel({ canDecide }: { canDecide: boolean }) {
  const [status, setStatus] = useState<string>('pending')
  const [priority, setPriority] = useState<string>('')
  const [offset, setOffset] = useState(0)
  const params = {
    status: (status || undefined) as DecisionStatus | undefined,
    priority: (priority || undefined) as RiskLevel | undefined,
    offset,
    limit: PAGE,
  }
  const query = useApiQuery(mlKeys.reorder(params), () => listReorderRecommendations(params), {
    keepPrevious: true,
  })
  const decide = useApiMutation(decideReorder, {
    invalidates: [mlKeys.all, ['purchase-orders']],
    successMessage: (r) =>
      r.purchase_order_id
        ? `Reorder of ${r.product.sku} approved: draft purchase order created`
        : `Reorder of ${r.product.sku} ${r.status}`,
  })
  return (
    <Panel
      intro="Products likely to run out within 14 days, highest risk first, with what to order and why. Approving records the decision."
      filters={
        <>
          <FilterSelect
            label="Decision"
            value={status}
            onChange={(v) => {
              setStatus(v)
              setOffset(0)
            }}
            options={STATUS_OPTIONS}
          />
          <FilterSelect
            label="Priority"
            value={priority}
            onChange={(v) => {
              setPriority(v)
              setOffset(0)
            }}
            options={RISK_OPTIONS.filter((o) => o.value !== 'low')}
          />
        </>
      }
      isLoading={query.isLoading}
      errorMessage={query.errorMessage}
      total={query.data?.total}
      offset={offset}
      onPage={setOffset}
    >
      <ReorderTable
        items={query.data?.items ?? []}
        canDecide={canDecide}
        busyId={decide.isPending ? decide.variables?.id : null}
        onDecide={(item: ReorderRecommendation, approve) => decide.mutate({ id: item.id, approve })}
      />
    </Panel>
  )
}

export function SlottingPanel({ canDecide }: { canDecide: boolean }) {
  const [status, setStatus] = useState<string>('pending')
  const [offset, setOffset] = useState(0)
  const params = {
    status: (status || undefined) as DecisionStatus | undefined,
    offset,
    limit: PAGE,
  }
  const query = useApiQuery(mlKeys.slotting(params), () => listSlottingRecommendations(params), {
    keepPrevious: true,
  })
  const decide = useApiMutation(decideSlotting, {
    invalidates: [mlKeys.all],
    successMessage: (r) => `New bin for ${r.product.sku} ${r.status}`,
  })
  const saved = (query.data?.items ?? []).reduce(
    (sum, i) => sum + (i.seconds_saved_per_day ?? 0),
    0,
  )
  return (
    <Panel
      intro="Better pick locations, biggest saving first: fast movers close to packing, heavy goods low. Zone, weight and volume limits are always kept."
      filters={
        <FilterSelect
          label="Decision"
          value={status}
          onChange={(v) => {
            setStatus(v)
            setOffset(0)
          }}
          options={STATUS_OPTIONS}
        />
      }
      isLoading={query.isLoading}
      errorMessage={query.errorMessage}
      total={query.data?.total}
      offset={offset}
      onPage={setOffset}
    >
      {saved > 0 && (
        <p className="text-sm text-slate-700">
          The moves on this page save about{' '}
          <span className="font-semibold">{formatNumber(Math.round(saved / 60))} minutes</span> of
          picking a day.
        </p>
      )}
      <SlottingList
        items={query.data?.items ?? []}
        canDecide={canDecide}
        busyId={decide.isPending ? decide.variables?.id : null}
        onDecide={(item: SlottingRecommendation, approve) =>
          decide.mutate({ id: item.id, approve })
        }
      />
    </Panel>
  )
}

export function DelayPanel() {
  const [risk, setRisk] = useState<string>('')
  const [offset, setOffset] = useState(0)
  const params = { risk_level: (risk || undefined) as RiskLevel | undefined, offset, limit: PAGE }
  const query = useApiQuery(mlKeys.delayRisks(params), () => listDelayRisks(params), {
    keepPrevious: true,
  })
  return (
    <Panel
      intro="Shipments on their way, most likely to arrive late first. Delays here are mostly chance, so treat the risk as an early warning, not a certainty."
      filters={
        <FilterSelect
          label="Risk level"
          value={risk}
          onChange={(v) => {
            setRisk(v)
            setOffset(0)
          }}
          options={RISK_OPTIONS}
        />
      }
      isLoading={query.isLoading}
      errorMessage={query.errorMessage}
      total={query.data?.total}
      offset={offset}
      onPage={setOffset}
    >
      <DelayRiskTable items={query.data?.items ?? []} />
    </Panel>
  )
}

export function MovementPanel() {
  const [movementClass, setMovementClass] = useState<string>('fast')
  const [offset, setOffset] = useState(0)
  const summary = useApiQuery(mlKeys.movementSummary, getMovementSummary)
  const params = {
    movement_class: (movementClass || undefined) as MovementClass | undefined,
    offset,
    limit: PAGE,
  }
  const list = useApiQuery(mlKeys.movements(params), () => listMovements(params), {
    keepPrevious: true,
  })
  return (
    <Panel
      intro="Fast, medium and slow movers from the last 90 days of picks. Slotting uses them to keep fast movers close to packing."
      isLoading={summary.isLoading}
      errorMessage={summary.errorMessage ?? list.errorMessage}
      total={list.data?.total}
      offset={offset}
      onPage={setOffset}
      filters={
        <FilterSelect
          label="Movement class"
          value={movementClass}
          onChange={(v) => {
            setMovementClass(v)
            setOffset(0)
          }}
          options={[
            { value: 'fast', label: 'Fast movers' },
            { value: 'medium', label: 'Medium movers' },
            { value: 'slow', label: 'Slow movers' },
            { value: '', label: 'All products' },
          ]}
        />
      }
    >
      <MovementMatrix summary={summary.data} />
      <ul className="divide-y divide-slate-100 text-sm" aria-label="Products by movement">
        {(list.data?.items ?? []).map((item) => (
          <li key={item.product.id} className="flex justify-between py-1.5">
            <span>
              <span className="font-medium">{item.product.sku}</span>{' '}
              <span className="text-slate-500">{item.product.name}</span>
            </span>
            <span className="text-slate-600 tabular-nums">
              {formatNumber(item.picks_per_day.toFixed(2))} picks/day
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}
