import type {
  DecisionStatus,
  DelayRiskPage,
  DemandForecast,
  ListParams,
  ModelSummary,
  MovementClass,
  MovementInfo,
  MovementPage,
  MovementSummary,
  OrderDelayRisk,
  ProductRecommendations,
  ReorderPage,
  ReorderRecommendation,
  RiskLevel,
  SlottingPage,
  SlottingRecommendation,
} from '../types/ml'
import { apiClient } from './apiClient'

/** Query keys: every ML list and detail lives under ['ml', ...]. */
export const mlKeys = {
  all: ['ml'] as const,
  models: ['ml', 'models'] as const,
  forecast: (productId: number) => ['ml', 'forecast', productId] as const,
  reorder: (params: object) => ['ml', 'reorder', params] as const,
  movement: (productId: number) => ['ml', 'movement', productId] as const,
  movements: (params: object) => ['ml', 'movements', params] as const,
  movementSummary: ['ml', 'movement-summary'] as const,
  slotting: (params: object) => ['ml', 'slotting', params] as const,
  delayRisk: (orderId: number) => ['ml', 'delay-risk', orderId] as const,
  delayRisks: (params: object) => ['ml', 'delay-risks', params] as const,
  recommendations: (productId: number) => ['ml', 'recommendations', productId] as const,
}

async function get<T>(path: string, params?: object): Promise<T> {
  const { data } = await apiClient.get<T>(`/ml/${path}`, { params })
  return data
}

export const getModels = () => get<ModelSummary[]>('models')

export const getDemandForecast = (productId: number) =>
  get<DemandForecast>(`demand-forecasts/${productId}`)

export const listReorderRecommendations = (
  params: ListParams & {
    status?: DecisionStatus
    priority?: RiskLevel
    warehouse_id?: number
  } = {},
) => get<ReorderPage>('reorder-recommendations', params)

export const getMovement = (productId: number) =>
  get<MovementInfo>(`movement-classification/${productId}`)

export const listMovements = (params: ListParams & { movement_class?: MovementClass } = {}) =>
  get<MovementPage>('movement-classifications', params)

export const getMovementSummary = () => get<MovementSummary>('movement-classifications/summary')

export const listSlottingRecommendations = (
  params: ListParams & { status?: DecisionStatus; warehouse_id?: number } = {},
) => get<SlottingPage>('slotting-recommendations', params)

export const getOrderDelayRisk = (orderId: number) => get<OrderDelayRisk>(`delay-risk/${orderId}`)

export const listDelayRisks = (params: ListParams & { risk_level?: RiskLevel } = {}) =>
  get<DelayRiskPage>('delay-risks', params)

export const getProductRecommendations = (productId: number) =>
  get<ProductRecommendations>(`product-recommendations/${productId}`)

export interface DecisionInput {
  id: number
  approve: boolean
  note?: string
}

async function decide<T>(kind: 'reorder' | 'slotting', input: DecisionInput): Promise<T> {
  const action = input.approve ? 'approve' : 'reject'
  const { data } = await apiClient.post<T>(
    `/ml/${kind}-recommendations/${input.id}/${action}`,
    input.note ? { note: input.note } : undefined,
  )
  return data
}

export const decideReorder = (input: DecisionInput) =>
  decide<ReorderRecommendation>('reorder', input)

export const decideSlotting = (input: DecisionInput) =>
  decide<SlottingRecommendation>('slotting', input)
