import { useId } from 'react'

import { PageHeader } from '../components/common/PageHeader'
import {
  DelayPanel,
  ModelsPanel,
  MovementPanel,
  ReorderPanel,
  SlottingPanel,
} from '../components/ml/MLPanels'
import { isOrderManager } from '../components/orders/orderFormat'
import { useAuth } from '../hooks/useAuth'
import { useUrlState } from '../hooks/useUrlState'

const TABS = [
  { view: 'reorder', label: 'Reorder' },
  { view: 'slotting', label: 'Slotting' },
  { view: 'delays', label: 'Delay risk' },
  { view: 'movement', label: 'Movement' },
  { view: 'models', label: 'Models' },
] as const

/**
 * ML insights (Phase 9): the predictions of the selected models, with their reasons.
 * Managers approve or reject reorder and slotting recommendations; staff can read.
 * Demand forecasts and related products are on each product's page.
 */
export default function MLInsightsPage() {
  const { user } = useAuth()
  const [url, setUrl] = useUrlState({ view: 'reorder' })
  const tabsId = useId()
  const active = TABS.find((t) => t.view === url.view) ?? TABS[0]
  const canDecide = isOrderManager(user)

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="ML insights"
        description="Recommendations and risks from the trained models, with the reasons behind them. Demand forecasts and related products are on each product page."
      />
      <div
        role="tablist"
        aria-label="ML insights"
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
        {active.view === 'reorder' && <ReorderPanel canDecide={canDecide} />}
        {active.view === 'slotting' && <SlottingPanel canDecide={canDecide} />}
        {active.view === 'delays' && <DelayPanel />}
        {active.view === 'movement' && <MovementPanel />}
        {active.view === 'models' && <ModelsPanel />}
      </div>
    </div>
  )
}
