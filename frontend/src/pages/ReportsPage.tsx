import { useId } from 'react'

import { PageHeader } from '../components/common/PageHeader'
import { DateRangePicker } from '../components/dashboard/DateRangePicker'
import { DEFAULT_RANGE, rangeParams, type DateRangeValue } from '../components/dashboard/dateRange'
import { isOrderManager } from '../components/orders/orderFormat'
import {
  FulfillmentReport,
  InventoryReport,
  SupplierReport,
  WarehouseReport,
} from '../components/reports/ReportPanels'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'

const TABS = [
  { view: 'inventory', label: 'Inventory', Panel: InventoryReport },
  { view: 'fulfillment', label: 'Fulfillment', Panel: FulfillmentReport },
  { view: 'warehouse', label: 'Warehouse', Panel: WarehouseReport },
  { view: 'suppliers', label: 'Suppliers', Panel: SupplierReport },
] as const

const URL_DEFAULTS = { view: 'inventory', range: DEFAULT_RANGE.preset as string, from: '', to: '' }

/** KPI reports per area (project document, section 9.4). One period for every tab. */
export default function ReportsPage() {
  const { user } = useAuth()
  const [url, setUrl] = useUrlState(URL_DEFAULTS)
  const tabsId = useId()
  const range: DateRangeValue = {
    preset: url.range as DateRangeValue['preset'],
    from: url.from,
    to: url.to,
  }
  const active = TABS.find((t) => t.view === url.view) ?? TABS[0]
  const { Panel } = active

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Reports"
        description="Inventory, fulfillment, warehouse and supplier KPIs for a period. Every chart has a table view with the exact numbers."
      />
      <DateRangePicker
        value={range}
        onChange={(next) => setUrl({ range: next.preset, from: next.from, to: next.to })}
      />
      <div
        role="tablist"
        aria-label="Report areas"
        className="flex gap-1 overflow-x-auto border-b border-slate-200"
      >
        {TABS.map((tab) => (
          <button
            key={tab.view}
            type="button"
            role="tab"
            id={`${tabsId}-${tab.view}`}
            aria-selected={tab.view === active.view}
            aria-controls={`${tabsId}-panel`}
            onClick={() => setUrl({ view: tab.view })}
            className={`-mb-px shrink-0 border-b-2 px-4 py-2 text-sm font-medium whitespace-nowrap ${
              tab.view === active.view
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${active.view}`}>
        <Panel range={rangeParams(range)} financials={isOrderManager(user)} />
      </div>
    </div>
  )
}
