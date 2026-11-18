import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './apiClient'
import {
  decideReorder,
  decideSlotting,
  getDemandForecast,
  getOrderDelayRisk,
  getProductRecommendations,
  listReorderRecommendations,
  mlKeys,
} from './mlApi'

afterEach(() => vi.restoreAllMocks())

describe('mlApi', () => {
  it('reads from /ml with the given filters', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [] } })
    await listReorderRecommendations({ status: 'pending', priority: 'high', limit: 20 })
    expect(get).toHaveBeenCalledWith('/ml/reorder-recommendations', {
      params: { status: 'pending', priority: 'high', limit: 20 },
    })
    await getDemandForecast(7)
    expect(get).toHaveBeenLastCalledWith('/ml/demand-forecasts/7', { params: undefined })
    await getOrderDelayRisk(3)
    expect(get).toHaveBeenLastCalledWith('/ml/delay-risk/3', { params: undefined })
    await getProductRecommendations(9)
    expect(get).toHaveBeenLastCalledWith('/ml/product-recommendations/9', { params: undefined })
  })

  it('approves and rejects, with a note only when given', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 1 } })
    await decideReorder({ id: 11, approve: true, note: 'Peak season' })
    expect(post).toHaveBeenCalledWith('/ml/reorder-recommendations/11/approve', {
      note: 'Peak season',
    })
    await decideSlotting({ id: 21, approve: false })
    expect(post).toHaveBeenLastCalledWith('/ml/slotting-recommendations/21/reject', undefined)
  })

  it('keeps every ML query under one key', () => {
    expect(mlKeys.forecast(7)).toEqual(['ml', 'forecast', 7])
    expect(mlKeys.reorder({ status: 'pending' })[0]).toBe('ml')
  })
})
