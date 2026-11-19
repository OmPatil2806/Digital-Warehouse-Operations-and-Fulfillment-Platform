/**
 * Every API function of the web app calls a route the backend really has.
 *
 * The page tests replace these functions with mocks, so a typo in a path would only
 * show up in the browser. Here each function is called once with sample arguments; the
 * request it makes (method + path) must match one of the backend's routes, listed in
 * src/test/apiRoutes.json (regenerate with `python scripts/export_api_routes.py`; the
 * backend tests fail when that file is out of date).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import routes from '../test/apiRoutes.json'
import * as alertsApi from './alertsApi'
import { apiClient } from './apiClient'
import * as catalogApi from './catalogApi'
import * as dashboardApi from './dashboardApi'
import * as fulfillmentApi from './fulfillmentApi'
import * as healthApi from './healthApi'
import * as inventoryApi from './inventoryApi'
import * as mlApi from './mlApi'
import * as ordersApi from './ordersApi'
import * as purchasingApi from './purchasingApi'
import * as usersApi from './usersApi'
import * as warehouseApi from './warehouseApi'

type Call = { method: string; path: string; params?: Record<string, unknown>; body?: unknown }

const calls: Call[] = []

beforeEach(() => {
  calls.length = 0
  const page = { items: [], total: 0, offset: 0, limit: 50 }
  for (const method of ['get', 'delete'] as const) {
    vi.spyOn(apiClient, method).mockImplementation(async (path: string, config?: unknown) => {
      const params = (config as { params?: Record<string, unknown> } | undefined)?.params
      calls.push({ method: method.toUpperCase(), path, params })
      return { data: page }
    })
  }
  for (const method of ['post', 'put', 'patch'] as const) {
    vi.spyOn(apiClient, method).mockImplementation(async (path: string, body?: unknown) => {
      calls.push({ method: method.toUpperCase(), path, body })
      return { data: page }
    })
  }
})

afterEach(() => vi.restoreAllMocks())

/** "GET /orders/{order_id}" -> a pattern matching "GET /orders/12". */
const patterns = routes.map((route) => ({
  route,
  regex: new RegExp(`^${route.replace(/\{[^}]+\}/g, '[^/]+')}$`),
}))

function routeOf(call: Call): string | undefined {
  const path = call.path.split('?')[0]
  return patterns.find((p) => p.regex.test(`${call.method} ${path}`))?.route
}

/** Every API function, called with sample arguments. */
const ALL_CALLS: [string, () => Promise<unknown>][] = [
  // health, alerts, audit
  ['getHealth', () => healthApi.getHealth()],
  ['listAlerts', () => alertsApi.listAlerts({ status: 'unresolved' })],
  ['getAlertSummary', () => alertsApi.getAlertSummary()],
  ['acknowledgeAlert', () => alertsApi.acknowledgeAlert(1)],
  ['resolveAlert', () => alertsApi.resolveAlert(1)],
  ['listAuditLogs', () => alertsApi.listAuditLogs({ entityType: 'product', entityId: 3 })],
  // catalog
  ['listCategories', () => catalogApi.listCategories()],
  ['listProducts', () => catalogApi.listProducts()],
  ['getProduct', () => catalogApi.getProduct(1)],
  ['createProduct', () => catalogApi.createProduct({} as never)],
  ['updateProduct', () => catalogApi.updateProduct(1, { is_active: false })],
  ['getProductSuppliers', () => catalogApi.getProductSuppliers(1)],
  ['listSuppliers', () => catalogApi.listSuppliers()],
  ['getSupplier', () => catalogApi.getSupplier(1)],
  ['createSupplier', () => catalogApi.createSupplier({} as never)],
  ['updateSupplier', () => catalogApi.updateSupplier(1, { is_active: true })],
  ['getSupplierProducts', () => catalogApi.getSupplierProducts(1)],
  ['addSupplierProduct', () => catalogApi.addSupplierProduct(1, {} as never)],
  ['removeSupplierProduct', () => catalogApi.removeSupplierProduct(1, 2)],
  // dashboards
  ['getOverviewDashboard', () => dashboardApi.getOverviewDashboard()],
  ['getInventoryDashboard', () => dashboardApi.getInventoryDashboard({}, 5)],
  ['getFulfillmentDashboard', () => dashboardApi.getFulfillmentDashboard()],
  ['getWarehouseDashboard', () => dashboardApi.getWarehouseDashboard()],
  ['getSupplierDashboard', () => dashboardApi.getSupplierDashboard()],
  // inventory
  ['listInventory', () => inventoryApi.listInventory({ productId: 1, includeEmpty: true })],
  ['getProductStock', () => inventoryApi.getProductStock(1)],
  ['listMovements', () => inventoryApi.listMovements({ productId: 1 })],
  ['receiveStock', () => inventoryApi.receiveStock({ product_id: 1, bin_id: 2, quantity: 3 })],
  [
    'submitAdjustment',
    () =>
      inventoryApi.submitAdjustment({
        product_id: 1,
        bin_id: 2,
        kind: 'decrease',
        quantity: 1,
        reason: 'Lost',
      }),
  ],
  [
    'submitTransfer',
    () => inventoryApi.submitTransfer({ product_id: 1, from_bin_id: 2, to_bin_id: 3, quantity: 1 }),
  ],
  ['getApprovalQueue', () => inventoryApi.getApprovalQueue()],
  ['listMyRequests', () => inventoryApi.listMyRequests()],
  ['decideRequest approve', () => inventoryApi.decideRequest('adjustments', 1, 'approve')],
  ['decideRequest reject', () => inventoryApi.decideRequest('transfers', 1, 'reject', 'No')],
  ['decideRequest cancel', () => inventoryApi.decideRequest('transfers', 1, 'cancel')],
  ['listCycleCounts', () => inventoryApi.listCycleCounts()],
  ['startCycleCount', () => inventoryApi.startCycleCount({ bin_id: 1 })],
  ['getCycleCount', () => inventoryApi.getCycleCount(1)],
  ['recordCounts', () => inventoryApi.recordCounts(1, [])],
  ['cycleCountAction submit', () => inventoryApi.cycleCountAction(1, 'submit')],
  ['cycleCountAction approve', () => inventoryApi.cycleCountAction(1, 'approve')],
  ['cycleCountAction reject', () => inventoryApi.cycleCountAction(1, 'reject', 'Recount')],
  ['cycleCountAction cancel', () => inventoryApi.cycleCountAction(1, 'cancel')],
  // orders and customers
  ['listOrders', () => ordersApi.listOrders()],
  ['getOrder', () => ordersApi.getOrder(1)],
  ['createOrder', () => ordersApi.createOrder({} as never)],
  ...(['confirm', 'cancel', 'hold', 'release', 'reserve'] as const).map(
    (action) =>
      [`orderAction ${action}`, () => ordersApi.orderAction(1, action, 'Reason')] as [
        string,
        () => Promise<unknown>,
      ],
  ),
  ['allocateOrder', () => ordersApi.allocateOrder(1)],
  ['getOrderShipment', () => ordersApi.getOrderShipment(1)],
  ['listOrderReturns', () => ordersApi.listOrderReturns(1)],
  ['listCustomers', () => ordersApi.listCustomers('acme')],
  ['getMyCustomer', () => ordersApi.getMyCustomer()],
  // fulfillment
  ['listPickingTasks', () => fulfillmentApi.listPickingTasks({ mine: true })],
  ['startPicking', () => fulfillmentApi.startPicking(1)],
  ['completePicking', () => fulfillmentApi.completePicking(1, {} as never)],
  ['listPackingTasks', () => fulfillmentApi.listPackingTasks()],
  ['startPacking', () => fulfillmentApi.startPacking(1)],
  ['completePacking', () => fulfillmentApi.completePacking(1, {} as never)],
  ['listCarriers', () => fulfillmentApi.listCarriers()],
  ['createShipment', () => fulfillmentApi.createShipment({} as never)],
  ['listShipments', () => fulfillmentApi.listShipments({ q: 'DHL' })],
  ['addShipmentEvent', () => fulfillmentApi.addShipmentEvent(1, {} as never)],
  ['checkDelays', () => fulfillmentApi.checkDelays()],
  ['listReturns', () => fulfillmentApi.listReturns({ order_id: 1 })],
  ['openReturn', () => fulfillmentApi.openReturn({} as never)],
  ['inspectReturn', () => fulfillmentApi.inspectReturn(1, [])],
  ['cancelReturn', () => fulfillmentApi.cancelReturn(1)],
  // purchasing
  ['listPurchaseOrders', () => purchasingApi.listPurchaseOrders({ overdue: true })],
  ['createPurchaseOrder', () => purchasingApi.createPurchaseOrder({} as never)],
  ['purchaseOrderAction order', () => purchasingApi.purchaseOrderAction(1, 'order')],
  ['purchaseOrderAction cancel', () => purchasingApi.purchaseOrderAction(1, 'cancel')],
  ['receivePurchaseOrder', () => purchasingApi.receivePurchaseOrder(1, [])],
  ['checkOverduePurchaseOrders', () => purchasingApi.checkOverduePurchaseOrders()],
  // users
  ['listUsers', () => usersApi.listUsers()],
  ['createUser', () => usersApi.createUser({} as never)],
  ['updateUser', () => usersApi.updateUser(1, {} as never)],
  ['deactivateUser', () => usersApi.deactivateUser(1)],
  // warehouse layout
  ['listWarehouses', () => warehouseApi.listWarehouses()],
  ['getLayout', () => warehouseApi.getLayout(1, true)],
  [
    'createWarehouse',
    () => warehouseApi.createWarehouse({ code: 'WH9', name: 'X', address: null }),
  ],
  ['createZone', () => warehouseApi.createZone(1, {} as never)],
  ['setZoneActive', () => warehouseApi.setZoneActive(1, false)],
  ['setRackActive', () => warehouseApi.setRackActive(1, true)],
  ['generateLayout', () => warehouseApi.generateLayout(1, {} as never)],
  ['getBinByCode', () => warehouseApi.getBinByCode(' WH01-ZA-R01-S01-B01 ')],
  ['checkFit', () => warehouseApi.checkFit(1, 2, 3)],
  // machine learning
  ['getModels', () => mlApi.getModels()],
  ['getMlSummary', () => mlApi.getMlSummary()],
  ['getAccuracy', () => mlApi.getAccuracy()],
  ['getDemandForecast', () => mlApi.getDemandForecast(1)],
  ['listReorderRecommendations', () => mlApi.listReorderRecommendations()],
  ['getMovement', () => mlApi.getMovement(1)],
  ['listMovements (ML)', () => mlApi.listMovements()],
  ['getMovementSummary', () => mlApi.getMovementSummary()],
  ['listSlottingRecommendations', () => mlApi.listSlottingRecommendations()],
  ['getOrderDelayRisk', () => mlApi.getOrderDelayRisk(1)],
  ['listDelayRisks', () => mlApi.listDelayRisks()],
  ['getProductRecommendations', () => mlApi.getProductRecommendations(1)],
  ['decideReorder', () => mlApi.decideReorder({ id: 1, approve: true })],
  ['decideSlotting', () => mlApi.decideSlotting({ id: 1, approve: false })],
]

describe('API functions', () => {
  it.each(ALL_CALLS)('%s calls a real backend route', async (_name, call) => {
    await call()
    expect(calls.length).toBeGreaterThan(0)
    for (const request of calls) {
      expect(routeOf(request), `${request.method} ${request.path}`).toBeDefined()
    }
  })

  it('notices a path the backend does not have', () => {
    expect(routeOf({ method: 'GET', path: '/orders/1' })).toBe('GET /orders/{order_id}')
    expect(routeOf({ method: 'GET', path: '/orders/1/nothing' })).toBeUndefined()
    expect(routeOf({ method: 'DELETE', path: '/orders/1' })).toBeUndefined()
  })

  it('covers every exported API function', () => {
    const modules = {
      alertsApi,
      catalogApi,
      dashboardApi,
      fulfillmentApi,
      healthApi,
      inventoryApi,
      mlApi,
      ordersApi,
      purchasingApi,
      usersApi,
      warehouseApi,
    }
    const exported = Object.values(modules).flatMap((module) =>
      Object.entries(module)
        .filter(([, value]) => typeof value === 'function')
        .map(([name]) => name),
    )
    const called = new Set(ALL_CALLS.map(([name]) => name.split(' ')[0]))
    called.add('listMovements')
    const missing = exported.filter((name) => !called.has(name))
    expect(missing).toEqual([])
  })

  it('sends filters with the backend names and leaves empty ones out', async () => {
    await alertsApi.listAlerts({ status: 'unresolved', alertType: 'low_stock' })
    expect(calls[0].params).toMatchObject({ unresolved: true, alert_type: 'low_stock' })
    expect(calls[0].params?.status).toBeUndefined()
    await inventoryApi.listInventory({ productId: 4, includeEmpty: false })
    expect(calls[1].params).toMatchObject({ product_id: 4 })
    expect(calls[1].params?.include_empty).toBeUndefined()
    await warehouseApi.getBinByCode(' WH01-ZA-R01-S01-B01 ')
    expect(calls[2].path).toBe('/bins/by-code/WH01-ZA-R01-S01-B01')
    await ordersApi.orderAction(1, 'confirm', 'ignored')
    expect(calls[3].body).toBeUndefined() // only cancel and hold send a reason
    await inventoryApi.decideRequest('transfers', 1, 'cancel', 'ignored')
    expect(calls[4].body).toBeUndefined()
  })
})
