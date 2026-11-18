import { screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as mlApi from '../../api/mlApi'
import { forecastFixture, recommendationsFixture, reorderFixture } from '../../test/mlFixtures'
import { loggedInAs, renderWithAuth } from '../../test/renderWithAuth'
import { MLSummaryCards } from './MLSummaryCards'
import { OrderDelayRisk } from './OrderDelayRisk'
import { ProductMLPanel } from './ProductMLPanel'
import { ReorderTable } from './ReorderTable'

vi.mock('../../api/mlApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/mlApi')>()),
  getDemandForecast: vi.fn(),
  getMovement: vi.fn(),
  getProductRecommendations: vi.fn(),
  getOrderDelayRisk: vi.fn(),
  getMlSummary: vi.fn(),
}))
const api = vi.mocked(mlApi)
const manager = { auth: loggedInAs('manager') }

beforeEach(() => {
  vi.clearAllMocks()
  api.getDemandForecast.mockResolvedValue(forecastFixture)
  api.getMovement.mockResolvedValue({
    product: forecastFixture.product,
    movement_class: 'fast',
    picks_per_day: 3.456,
    scored_at: '2026-11-18T12:00:00Z',
    as_of: '2026-11-10',
  })
  api.getProductRecommendations.mockResolvedValue(recommendationsFixture)
})

describe('ProductMLPanel', () => {
  it('shows the forecast, the movement class and related products', async () => {
    renderWithAuth(<ProductMLPanel productId={7} />, manager)
    expect(await screen.findByText('Fast mover')).toBeInTheDocument()
    expect(screen.getByText(/3.46 picks\/day recently/)).toBeInTheDocument()
    expect(screen.getByText('Next 7 days')).toBeInTheDocument()
    const related = screen.getByRole('list', { name: 'Frequently bought together' })
    expect(within(related).getAllByRole('listitem')).toHaveLength(2)
    expect(api.getDemandForecast).toHaveBeenCalledWith(7)
  })

  it('leaves out the movement class when there is none', async () => {
    api.getMovement.mockRejectedValue(new Error('404'))
    renderWithAuth(<ProductMLPanel productId={7} />, manager)
    expect(await screen.findByText('Next 7 days')).toBeInTheDocument()
    expect(screen.queryByText(/mover$/)).not.toBeInTheDocument()
  })
})

describe('OrderDelayRisk', () => {
  it('shows the risk and its reasons for a shipment on its way', async () => {
    api.getOrderDelayRisk.mockResolvedValue({
      order_id: 4,
      prediction: {
        order_id: 4,
        order_number: 'SO-2026-000004',
        shipment_id: 9,
        probability: 0.56,
        risk_level: 'high',
        reasons: ['Waited for stock', 'Peak season'],
        scored_at: '2026-11-18T12:00:00Z',
        as_of: '2026-11-10',
      },
    })
    renderWithAuth(<OrderDelayRisk orderId={4} />, manager)
    const panel = await screen.findByRole('region', { name: 'Delivery risk' })
    expect(panel).toHaveTextContent('High risk56 %')
    expect(panel).toHaveTextContent('Main reasons: Waited for stock; Peak season')
    expect(panel).toHaveTextContent('As of 10 Nov')
  })

  it('shows nothing when the order is not on its way', async () => {
    api.getOrderDelayRisk.mockResolvedValue({ order_id: 4, prediction: null })
    const { container } = renderWithAuth(<OrderDelayRisk orderId={4} />, manager)
    await vi.waitFor(() => expect(api.getOrderDelayRisk).toHaveBeenCalled())
    expect(container.querySelector('section')).toBeNull()
  })
})

describe('MLSummaryCards', () => {
  it('explains what to do before anything is scored', async () => {
    api.getMlSummary.mockResolvedValue({
      as_of: null,
      stockouts_high: 0,
      stockouts_pending: 0,
      orders_high_risk: 0,
      orders_at_risk: 0,
      orders_on_the_way: 0,
      forecast_units_7_days: 0,
      forecast_units_30_days: 0,
      slotting_pending: 0,
      slotting_seconds_saved_per_day: 0,
    })
    renderWithAuth(<MLSummaryCards />, manager)
    expect(await screen.findByText(/No predictions yet/)).toBeInTheDocument()
  })
})

describe('ReorderTable after approval', () => {
  it('links to the drafted purchase order', () => {
    renderWithAuth(
      <ReorderTable
        items={[reorderFixture({ status: 'approved', purchase_order_id: 31 })]}
        canDecide
      />,
      manager,
    )
    expect(screen.getByRole('link', { name: 'Draft purchase order created' })).toHaveAttribute(
      'href',
      '/purchase-orders',
    )
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  })
})
