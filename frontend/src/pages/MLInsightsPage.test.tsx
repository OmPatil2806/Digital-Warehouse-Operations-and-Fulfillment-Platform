import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as mlApi from '../api/mlApi'
import { AuthContext } from '../context/authContext'
import { AppRoutes } from '../routes/AppRoutes'
import { page } from '../test/catalogFixtures'
import {
  movementSummaryFixture,
  predictionCheckFixture,
  reorderFixture,
  slottingFixture,
} from '../test/mlFixtures'
import { loggedInAs, renderWithAuth } from '../test/renderWithAuth'
import { TestProviders } from '../test/TestProviders'
import type { ModelSummary } from '../types/ml'
import MLInsightsPage from './MLInsightsPage'

vi.mock('../api/mlApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/mlApi')>()),
  getModels: vi.fn(),
  getAccuracy: vi.fn(),
  listReorderRecommendations: vi.fn(),
  decideReorder: vi.fn(),
  listSlottingRecommendations: vi.fn(),
  decideSlotting: vi.fn(),
  listDelayRisks: vi.fn(),
  getMovementSummary: vi.fn(),
  listMovements: vi.fn(),
}))
const api = vi.mocked(mlApi)

const MODELS: ModelSummary[] = [
  {
    use_case: 'reorder',
    model_name: 'lstm',
    version: 'v1',
    is_baseline: false,
    dataset_version: 'd',
    trained_at: '2026-11-16T12:00:00Z',
    test_metrics: { pr_auc: 0.328 },
    scored_at: '2026-11-18T12:00:00Z',
    as_of: '2026-11-10',
    predictions: 2435,
  },
  {
    use_case: 'movement_classification',
    model_name: 'abc',
    version: 'v1',
    is_baseline: true,
    dataset_version: 'd',
    trained_at: '2026-11-16T12:00:00Z',
    test_metrics: { fast_pick_share: 0.785 },
    scored_at: null,
    as_of: null,
    predictions: 0,
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  api.listReorderRecommendations.mockResolvedValue(page([reorderFixture()], 30))
  api.decideReorder.mockResolvedValue(reorderFixture({ status: 'approved' }))
  api.listSlottingRecommendations.mockResolvedValue(page([slottingFixture()]))
  api.decideSlotting.mockResolvedValue(slottingFixture({ status: 'rejected' }))
  api.getModels.mockResolvedValue(MODELS)
  api.getAccuracy.mockResolvedValue(predictionCheckFixture)
  api.listDelayRisks.mockResolvedValue(
    page([
      {
        order_id: 4,
        order_number: 'SO-2026-000004',
        shipment_id: 9,
        probability: 0.56,
        risk_level: 'high',
        reasons: ['Waited for stock', 'Peak season'],
        scored_at: '2026-11-18T12:00:00Z',
        as_of: '2026-11-10',
      },
    ]),
  )
  api.getMovementSummary.mockResolvedValue(movementSummaryFixture)
  api.listMovements.mockResolvedValue(
    page([
      {
        product: { id: 7, sku: 'ELE-00007', name: 'Monitor' },
        movement_class: 'fast',
        picks_per_day: 3.25,
        scored_at: '2026-11-18T12:00:00Z',
        as_of: '2026-11-10',
      },
    ]),
  )
})

describe('MLInsightsPage', () => {
  it('opens on pending reorder recommendations; managers approve them', async () => {
    const user = userEvent.setup()
    renderWithAuth(<MLInsightsPage />, { auth: loggedInAs('manager'), path: '/ml-insights' })

    expect(await screen.findByRole('link', { name: 'ELE-00007' })).toBeInTheDocument()
    expect(api.listReorderRecommendations).toHaveBeenCalledWith({
      status: 'pending',
      priority: undefined,
      offset: 0,
      limit: 25,
    })
    expect(screen.getByText(/Showing/)).toHaveTextContent('Showing 1–25 of 30')

    await user.click(screen.getByRole('button', { name: 'Approve reorder of ELE-00007 for WH01' }))
    await waitFor(() =>
      expect(api.decideReorder.mock.calls[0]?.[0]).toEqual({ id: 11, approve: true }),
    )
    expect(await screen.findByText('Reorder of ELE-00007 approved')).toBeInTheDocument()
    await waitFor(() => expect(api.listReorderRecommendations).toHaveBeenCalledTimes(2)) // reloaded
  })

  it('filters by decision and priority, back to the first page', async () => {
    const user = userEvent.setup()
    renderWithAuth(<MLInsightsPage />, { auth: loggedInAs('manager'), path: '/ml-insights' })
    await screen.findByRole('link', { name: 'ELE-00007' })

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Priority' }), 'high')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Decision' }), '')
    await waitFor(() =>
      expect(api.listReorderRecommendations).toHaveBeenLastCalledWith({
        status: undefined,
        priority: 'high',
        offset: 0,
        limit: 25,
      }),
    )
  })

  it('staff can read but not decide', async () => {
    renderWithAuth(<MLInsightsPage />, { auth: loggedInAs('staff'), path: '/ml-insights' })
    expect(await screen.findByRole('link', { name: 'ELE-00007' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Approve/ })).not.toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Reorder recommendations' })
    expect(within(table).getByText('Pending')).toBeInTheDocument()
  })

  it('shows slotting moves with the time they save and lets managers reject', async () => {
    const user = userEvent.setup()
    renderWithAuth(<MLInsightsPage />, {
      auth: loggedInAs('manager'),
      path: '/ml-insights?view=slotting',
    })
    expect(await screen.findByText(/save about/)).toHaveTextContent('save about 10 minutes')
    await user.click(screen.getByRole('button', { name: /^Reject new bin for ELE-00007/ }))
    await waitFor(() =>
      expect(api.decideSlotting.mock.calls[0]?.[0]).toEqual({ id: 21, approve: false }),
    )
  })

  it('switches tabs and keeps the tab in the address bar', async () => {
    const user = userEvent.setup()
    renderWithAuth(<MLInsightsPage />, { auth: loggedInAs('manager'), path: '/ml-insights' })
    await screen.findByRole('link', { name: 'ELE-00007' })

    await user.click(screen.getByRole('tab', { name: 'Delay risk' }))
    const delay = await screen.findByRole('link', { name: 'SO-2026-000004' })
    expect(delay).toHaveAttribute('href', '/orders/4')
    expect(screen.getByText('Waited for stock; Peak season')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/ml-insights?view=delays')

    await user.click(screen.getByRole('tab', { name: 'Movement' }))
    expect(await screen.findByRole('row', { name: /Fast movers/ })).toHaveTextContent('80 %')
    const list = screen.getByRole('list', { name: 'Products by movement' })
    expect(within(list).getByText('3.25 picks/day')).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Models' }))
    const table = await screen.findByRole('table', { name: 'Models in use' })
    const reorder = within(table).getByRole('row', { name: /Reorder recommendation/ })
    expect(reorder).toHaveTextContent('Neural network')
    expect(reorder).toHaveTextContent('0.328')
    expect(reorder).toHaveTextContent('2,435 as of 10 Nov')
    const movement = within(table).getByRole('row', { name: /Movement classification/ })
    expect(movement).toHaveTextContent('Baseline')
    expect(movement).toHaveTextContent('79 %')
    expect(movement).toHaveTextContent('Not scored yet')

    // Predictions vs reality, below the models
    expect(await screen.findByText(/orders known up to 10 Nov/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Demand forecast of 11 Oct' })).toHaveTextContent(
      'Forecast error26 %',
    )
    expect(screen.getByRole('region', { name: 'Delivery risks of 11 Oct' })).toHaveTextContent(
      '326 of 1,800 delivered parcels arrived late',
    )
  })

  it('shows errors from the API', async () => {
    api.listReorderRecommendations.mockRejectedValue(new Error('Network down'))
    renderWithAuth(<MLInsightsPage />, { auth: loggedInAs('manager'), path: '/ml-insights' })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('is not available to customers', async () => {
    render(
      <TestProviders>
        <AuthContext value={loggedInAs('customer')}>
          <MemoryRouter initialEntries={['/ml-insights']}>
            <AppRoutes />
          </MemoryRouter>
        </AuthContext>
      </TestProviders>,
    )
    expect(await screen.findByRole('heading', { name: 'Access denied' })).toBeInTheDocument()
    expect(api.listReorderRecommendations).not.toHaveBeenCalled()
  })
})
