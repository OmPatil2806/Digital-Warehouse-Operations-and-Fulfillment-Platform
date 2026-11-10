"""Responses of the dashboard (KPI) endpoints.

Money values are `None` for users who may not see costs (staff); the numbers they do
see are the same as a manager's.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class Period(BaseModel):
    """The date range the period KPIs cover (both days included, UTC)."""

    date_from: date
    date_to: date
    days: int


class InventoryOverview(BaseModel):
    value_at_cost: Decimal | None  # on-hand units x purchase cost
    units_on_hand: int
    units_available: int  # on hand - reserved - damaged, in active bins
    units_reserved: int
    units_damaged: int
    low_stock_products: int  # active products below their minimum stock
    out_of_stock_products: int  # active products with nothing available


class OrdersOverview(BaseModel):
    open: int  # placed but not shipped yet (and not cancelled)
    backordered: int  # waiting for stock (backordered or partially allocated)
    on_hold: int
    placed_in_period: int
    shipped_in_period: int
    delivered_in_period: int
    shipped_today: int


class ShipmentsOverview(BaseModel):
    on_the_way: int  # dispatched, in transit or delayed
    delayed: int


class AlertsOverview(BaseModel):
    unresolved: int
    critical: int


class PurchasingOverview(BaseModel):
    open: int  # ordered or partially received
    overdue: int
    open_value: Decimal | None  # value of the units still outstanding


class OverviewDashboard(BaseModel):
    period: Period
    include_financials: bool
    inventory: InventoryOverview
    orders: OrdersOverview
    shipments: ShipmentsOverview
    alerts: AlertsOverview
    purchasing: PurchasingOverview


# ========================================================================= inventory
class InventoryTotals(BaseModel):
    value_at_cost: Decimal | None
    value_at_price: Decimal | None  # what the stock would sell for
    units_on_hand: int
    units_available: int
    units_reserved: int
    units_damaged: int
    units_picked: int  # left the warehouse for orders in the period


class StockStatusCounts(BaseModel):
    """Active products by availability (each product counted once)."""

    ok: int  # at or above the minimum stock
    low: int  # some available, but below the minimum
    out: int  # nothing available


class CategoryStock(BaseModel):
    category_id: int
    category: str
    products: int
    units_on_hand: int
    value_at_cost: Decimal | None
    value_at_price: Decimal | None


class ProductStockKpi(BaseModel):
    product_id: int
    sku: str
    name: str
    category: str
    status: str  # ok / low / out
    min_stock: int
    units_on_hand: int
    units_available: int
    units_picked: int
    avg_daily_demand: Decimal  # units picked per day in the period
    days_of_supply: Decimal | None  # available / daily demand; None without demand
    turnover: Decimal | None  # units picked / average units on hand
    value_at_cost: Decimal | None


class InventoryDashboard(BaseModel):
    period: Period
    include_financials: bool
    totals: InventoryTotals
    # Cost of units picked / average stock value at cost, in the period.
    turnover: Decimal | None
    # Days the available stock lasts at the period's picking rate (by value at cost).
    days_of_supply: Decimal | None
    stock_status: StockStatusCounts
    by_category: list[CategoryStock]
    products: list[ProductStockKpi]  # most urgent first (fewest days of supply)
    products_total: int


# ======================================================================= fulfillment
class OrdersPerDay(BaseModel):
    day: date
    placed: int
    shipped: int
    delivered: int


class FulfillmentTotals(BaseModel):
    placed: int
    shipped: int
    delivered: int
    cancelled: int


class DurationKpi(BaseModel):
    """Average and median of a duration, over the orders it could be measured for."""

    orders: int
    average_hours: Decimal | None
    median_hours: Decimal | None


class RateKpi(BaseModel):
    """`good` of `total`, as a percentage (None when there is nothing to measure)."""

    good: int
    total: int
    percent: Decimal | None


class StatusCount(BaseModel):
    status: str
    count: int


class FulfillmentDashboard(BaseModel):
    period: Period
    totals: FulfillmentTotals
    per_day: list[OrdersPerDay]  # every day of the period, also days without orders
    # Confirmed -> shipped, for orders shipped in the period.
    fulfillment_time: DurationKpi
    # Placed -> delivered, for orders delivered in the period.
    cycle_time: DurationKpi
    # Shipments delivered in the period by their expected delivery date.
    on_time_delivery: RateKpi
    # Picking tasks finished in the period without a short pick.
    picking_accuracy: RateKpi
    by_status: list[StatusCount]  # all orders now, every status in flow order


# ========================================================================= warehouse
class SpaceUse(BaseModel):
    """Bins and capacity of active bins, and how much of it is used now."""

    bins: int
    occupied_bins: int  # holding at least one unit
    occupancy_percent: Decimal | None
    max_weight_kg: Decimal
    used_weight_kg: Decimal
    weight_percent: Decimal | None
    max_volume_cm3: int
    used_volume_cm3: Decimal
    volume_percent: Decimal | None


class ZoneUse(SpaceUse):
    zone_id: int
    warehouse: str
    code: str
    name: str
    zone_type: str
    is_active: bool
    picks: int  # pick movements from its bins in the period
    units_picked: int


class WarehouseDashboard(BaseModel):
    period: Period  # for the picks; space use is the state now
    total: SpaceUse
    zones: list[ZoneUse]  # by warehouse and zone code


# ========================================================================= suppliers
class SupplierKpi(BaseModel):
    supplier_id: int
    code: str
    name: str
    is_active: bool
    promised_lead_time_days: int  # the supplier's stated lead time
    reliability_score: Decimal  # stored rating (0-1); Phase 8 learns a better one
    received_orders: int  # purchase orders fully received in the period
    lead_time_avg_days: Decimal | None  # ordered -> fully received
    lead_time_variance: Decimal | None  # population variance, in days²
    lead_time_stddev_days: Decimal | None
    on_time: RateKpi  # fully received by the expected date
    open_orders: int
    overdue_orders: int
    open_value: Decimal | None  # value still outstanding (managers only)


class SupplierDashboard(BaseModel):
    period: Period
    include_financials: bool
    received_orders: int
    lead_time_avg_days: Decimal | None
    lead_time_variance: Decimal | None
    lead_time_stddev_days: Decimal | None
    on_time: RateKpi
    open_orders: int
    overdue_orders: int
    open_value: Decimal | None
    suppliers: list[SupplierKpi]  # active suppliers and any with purchase orders
