import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import {
  forecastFixture,
  movementSummaryFixture,
  predictionCheckFixture,
  recommendationsFixture,
  reorderFixture,
  slottingFixture,
} from '../../test/mlFixtures'
import { ForecastChart } from './ForecastChart'
import {
  formatBias,
  formatProbability,
  formatSecondsPerDay,
  formatShare,
  formatUnits,
  modelLabel,
} from './mlFormat'
import { MovementMatrix } from './MovementMatrix'
import { PredictionCheckView } from './PredictionCheck'
import { RecommendationList } from './RecommendationList'
import { ReorderTable } from './ReorderTable'
import { RiskBadge } from './RiskBadge'
import { SlottingList } from './SlottingList'

const withRouter = (ui: ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('ML formatting', () => {
  it('formats probabilities, time, units and model names', () => {
    expect(formatProbability(0.62)).toBe('62 %')
    expect(formatProbability(0.034)).toBe('3.4 %')
    expect(formatSecondsPerDay(45)).toBe('45 s/day')
    expect(formatSecondsPerDay(600)).toBe('10 min/day')
    expect(formatSecondsPerDay(5400)).toBe('1.5 h/day')
    expect(formatSecondsPerDay(null)).toBe('—')
    expect(formatUnits(0.44)).toBe('0.4')
    expect(formatUnits(12.6)).toBe('13')
    expect(modelLabel('lstm_events', false)).toBe('lstm events model')
    expect(modelLabel('abc', true)).toBe('baseline: abc')
    expect(formatBias(0.04)).toBe('4 % too high')
    expect(formatBias(-0.1)).toBe('10 % too low')
    expect(formatBias(0.001)).toBe('on target')
    expect(formatBias(null)).toBe('—')
    expect(formatShare(null)).toBe('—')
    expect(formatShare(0.863)).toBe('86 %')
  })
})

describe('PredictionCheckView', () => {
  it('compares the forecast with the orders that followed', async () => {
    render(<PredictionCheckView check={predictionCheckFixture} />)
    const demand = screen.getByRole('region', { name: 'Demand forecast of 11 Oct' })
    expect(demand).toHaveTextContent('lstm model · 2,000 products · 30 of 30 forecast days')
    expect(demand).toHaveTextContent(
      "Forecast error26 %Of each product's 30-day total; 25 % in testing",
    )
    expect(demand).toHaveTextContent('All products together4.2 % too low94,930 forecast, 99,117')
    expect(demand).toHaveTextContent('Inside the likely range86 %')
    await userEvent.setup().click(within(demand).getByRole('button', { name: /table/i }))
    expect(within(demand).getByRole('row', { name: /12 Oct/ })).toHaveTextContent(
      '12 Oct3,1003,250',
    )
  })

  it('shows how many parcels of each risk level arrived late', () => {
    render(<PredictionCheckView check={predictionCheckFixture} />)
    const delay = screen.getByRole('region', { name: 'Delivery risks of 11 Oct' })
    expect(delay).toHaveTextContent(
      'The model had marked 35 % of the late ones as medium or high risk. 11 are still on their way.',
    )
    const table = within(delay).getByRole('table', { name: 'Late deliveries by predicted risk' })
    expect(within(table).getByRole('row', { name: /Medium risk/ })).toHaveTextContent(
      '47647611424 %',
    )
    expect(within(table).getByRole('row', { name: /Low risk/ })).toHaveTextContent('16 %')
  })

  it('explains how to check before any day has passed', () => {
    render(<PredictionCheckView check={{ data_until: '2026-11-10', demand: null, delay: null }} />)
    expect(screen.getByText(/Nothing to check yet/)).toHaveTextContent('--backtest 30')
  })

  it('shows only what can be checked', () => {
    render(<PredictionCheckView check={{ ...predictionCheckFixture, demand: null }} />)
    expect(screen.queryByRole('region', { name: /Demand forecast/ })).toBeNull()
    expect(screen.getByRole('region', { name: /Delivery risks/ })).toBeInTheDocument()
  })
})

describe('RiskBadge', () => {
  it('shows the level in words with an icon and the probability', () => {
    render(<RiskBadge level="high" probability={0.62} />)
    const badge = screen.getByText('High risk').closest('span') as HTMLElement
    expect(badge).toHaveTextContent('High risk62 %')
    expect(badge.querySelector('svg')).not.toBeNull() // never colour alone
  })
})

describe('ForecastChart', () => {
  it('shows totals, where the forecast comes from, and the exact numbers as a table', async () => {
    const user = userEvent.setup()
    render(<ForecastChart forecast={forecastFixture} />)
    expect(screen.getByText('Next 7 days')).toBeInTheDocument()
    expect(screen.getByText('38')).toBeInTheDocument()
    expect(screen.getByText(/As of 10 Nov · lstm model/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /table/i }))
    const table = screen.getByRole('table', { name: 'Demand forecast' })
    const rows = within(table).getAllByRole('row')
    expect(within(rows[1]).getByRole('rowheader')).toHaveTextContent('11 Nov')
    expect(rows[2]).toHaveTextContent('13420') // 12.6 -> 13, low 4, high 20
  })

  it('explains when there is no forecast yet', () => {
    render(<ForecastChart forecast={{ ...forecastFixture, days: [], totals: [], scoring: null }} />)
    expect(screen.getByText(/No forecast yet/)).toBeInTheDocument()
  })
})

describe('ReorderTable', () => {
  it('lists risk, quantity and reasons; managers approve or reject', async () => {
    const onDecide = vi.fn()
    const user = userEvent.setup()
    const item = reorderFixture()
    withRouter(<ReorderTable items={[item]} canDecide onDecide={onDecide} />)
    const row = screen.getAllByRole('row')[1]
    expect(within(row).getByRole('link', { name: 'ELE-00007' })).toHaveAttribute(
      'href',
      '/products/7',
    )
    expect(row).toHaveTextContent('High risk82 %')
    expect(row).toHaveTextContent('63')
    expect(row).toHaveTextContent('Low available stock; Seasonal peak ahead')
    await user.click(
      within(row).getByRole('button', { name: 'Approve reorder of ELE-00007 for WH01' }),
    )
    expect(onDecide).toHaveBeenCalledWith(item, true)
    await user.click(
      within(row).getByRole('button', { name: 'Reject reorder of ELE-00007 for WH01' }),
    )
    expect(onDecide).toHaveBeenLastCalledWith(item, false)
  })

  it('staff see the status but no buttons; decided rows show the decision', () => {
    withRouter(
      <ReorderTable
        items={[
          reorderFixture(),
          reorderFixture({
            id: 12,
            status: 'approved',
            decided_at: '2026-11-11T09:00:00Z',
            decision_note: 'Peak season',
          }),
        ]}
        canDecide={false}
      />,
    )
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
    expect(screen.getByText('Pending')).toBeInTheDocument()
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(screen.getByText('“Peak season”')).toBeInTheDocument()
  })

  it('says when there is nothing to reorder', () => {
    withRouter(<ReorderTable items={[]} canDecide />)
    expect(screen.getByText('No reorder recommendations.')).toBeInTheDocument()
  })
})

describe('SlottingList', () => {
  it('shows the move, the time saved and the decision', async () => {
    const onDecide = vi.fn()
    const user = userEvent.setup()
    const item = slottingFixture()
    withRouter(<SlottingList items={[item]} canDecide onDecide={onDecide} />)
    const entry = within(screen.getByRole('list', { name: 'Slotting recommendations' })).getByRole(
      'listitem',
    )
    expect(entry).toHaveTextContent('WH01-ZB-R09-S04-B02')
    expect(entry).toHaveTextContent('95.5 m to packing · level 4')
    expect(entry).toHaveTextContent('WH01-ZA-R01-S01-B01')
    expect(entry).toHaveTextContent('10 min/day less picking')
    await user.click(within(entry).getByRole('button', { name: /^Approve new bin for ELE-00007/ }))
    expect(onDecide).toHaveBeenCalledWith(item, true)
  })

  it('handles products without a pick location yet', () => {
    withRouter(
      <SlottingList
        items={[
          slottingFixture({
            current_bin: null,
            current_seconds_per_day: null,
            seconds_saved_per_day: null,
          }),
        ]}
        canDecide={false}
      />,
    )
    expect(screen.getByText('No pick location yet')).toBeInTheDocument()
    expect(screen.getByText('5 min/day of picking there')).toBeInTheDocument()
  })
})

describe('MovementMatrix', () => {
  it('compares the share of products with the share of picks', () => {
    render(<MovementMatrix summary={movementSummaryFixture} />)
    const fast = screen.getByRole('row', { name: /Fast movers/ })
    expect(fast).toHaveTextContent('2') // products
    expect(fast).toHaveTextContent('20 %') // of products
    expect(fast).toHaveTextContent('80 %') // of picks
    expect(screen.getByText(/baseline: abc/)).toBeInTheDocument()
  })

  it('says when nothing is classified yet', () => {
    render(<MovementMatrix summary={undefined} />)
    expect(screen.getByText('No movement classes yet.')).toBeInTheDocument()
  })
})

describe('RecommendationList', () => {
  it('lists related products in rank order with links', () => {
    withRouter(<RecommendationList recommendations={recommendationsFixture} limit={1} />)
    const items = within(
      screen.getByRole('list', { name: 'Frequently bought together' }),
    ).getAllByRole('listitem')
    expect(items).toHaveLength(1)
    expect(within(items[0]).getByRole('link', { name: 'ACC-00008' })).toHaveAttribute(
      'href',
      '/products/8',
    )
  })

  it('says when there are none', () => {
    withRouter(<RecommendationList recommendations={undefined} />)
    expect(screen.getByText('No related products yet.')).toBeInTheDocument()
  })
})
