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
