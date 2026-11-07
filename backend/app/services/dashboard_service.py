"""KPI aggregation for the dashboards (project document, section 9.4).

All numbers are computed from the operational tables, so they always agree with the
rest of the application:

- *Stock* KPIs (inventory, open orders, shipments on the way, alerts, open purchase
  orders) describe the warehouse **now**.
- *Period* KPIs (orders placed, shipped, delivered) count events inside the chosen date
  range. Both days are included; days are UTC days.

Sums of money are calculated per product in Python from exact `Decimal` prices, never
with floating point.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.exceptions import UnprocessableError
from app.models.audit import Alert, AlertSeverity
from app.models.catalog import Product
from app.models.inventory import Inventory
from app.models.order import Order, OrderStatus
from app.models.purchase import OPEN_PO_STATUSES, PurchaseOrder, PurchaseOrderItem
from app.models.shipment import Shipment, ShipmentStatus
from app.models.warehouse import Bin
from app.schemas.dashboard import (
    AlertsOverview,
    InventoryOverview,
    OrdersOverview,
    OverviewDashboard,
    Period,
    PurchasingOverview,
    ShipmentsOverview,
)
from app.services.alert_service import UNRESOLVED

DEFAULT_DAYS = 30
MAX_DAYS = 366

# Orders that left the warehouse or will never leave it.
NOT_OPEN = (
    OrderStatus.SHIPPED,
    OrderStatus.DELAYED,
    OrderStatus.DELIVERED,
    OrderStatus.RETURNED,
    OrderStatus.CANCELLED,
)
WAITING_FOR_STOCK = (OrderStatus.BACKORDERED, OrderStatus.PARTIALLY_ALLOCATED)
ON_THE_WAY = (ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT, ShipmentStatus.DELAYED)


def _values(statuses: Iterable[str]) -> list[str]:
    return [str(s) for s in statuses]


@dataclass(frozen=True)
class DateRange:
    date_from: date
    date_to: date

    @classmethod
    def resolve(
        cls, date_from: date | None, date_to: date | None, *, today: date | None = None
    ) -> "DateRange":
        """Fill in missing ends and validate.

        No dates: the last 30 days up to today. Only an end: the 30 days up to it.
        Only a start: from it up to today.
        """
        today = today or datetime.now(UTC).date()
        end = date_to or today
        start = date_from or end - timedelta(days=DEFAULT_DAYS - 1)
        if start > end:
            raise UnprocessableError("The start date must not be after the end date")
        if (end - start).days + 1 > MAX_DAYS:
            raise UnprocessableError(f"The date range can be at most {MAX_DAYS} days")
        return cls(start, end)

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    @property
    def start(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=UTC)

    @property
    def end(self) -> datetime:
        """Exclusive: midnight after the last day."""
        return datetime.combine(self.date_to + timedelta(days=1), time.min, tzinfo=UTC)

    def period(self) -> Period:
        return Period(date_from=self.date_from, date_to=self.date_to, days=self.days)


class DashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --------------------------------------------------------------- overview
    def overview(
        self, period: DateRange, *, include_financials: bool, now: datetime | None = None
    ) -> OverviewDashboard:
        now = now or datetime.now(UTC)
        inventory = self.inventory_overview()
        purchasing = self.purchasing_overview(today=now.date())
        if not include_financials:
            inventory.value_at_cost = None
            purchasing.open_value = None
        return OverviewDashboard(
            period=period.period(),
            include_financials=include_financials,
            inventory=inventory,
            orders=self.orders_overview(period, now=now),
            shipments=self.shipments_overview(),
            alerts=self.alerts_overview(),
            purchasing=purchasing,
        )

    def inventory_overview(self) -> InventoryOverview:
        """Stock now. Units in archived bins count as on hand but never as available."""
        active = Bin.is_active.is_(True)
        available_expr = (
            Inventory.quantity_on_hand - Inventory.quantity_reserved - Inventory.quantity_damaged
        )
        rows = self.db.execute(
            select(
                Inventory.product_id,
                func.sum(Inventory.quantity_on_hand),
                func.sum(Inventory.quantity_reserved),
                func.sum(Inventory.quantity_damaged),
                func.sum(_where(active, available_expr)),
            )
            .join(Bin, Inventory.bin_id == Bin.id)
            .group_by(Inventory.product_id)
        ).all()
        stock = {pid: (int(oh), int(rs), int(dm), int(av or 0)) for pid, oh, rs, dm, av in rows}
        products = self.db.scalars(select(Product)).all()

        value = Decimal("0")
        low = out = 0
        for product in products:
            on_hand, _, _, available = stock.get(product.id, (0, 0, 0, 0))
            value += product.unit_cost * on_hand
            if not product.is_active:
                continue
            if available == 0:
                out += 1
            if available < product.min_stock:  # min_stock 0 never counts
                low += 1
        return InventoryOverview(
            value_at_cost=value.quantize(Decimal("0.01")),
            units_on_hand=sum(s[0] for s in stock.values()),
            units_reserved=sum(s[1] for s in stock.values()),
            units_damaged=sum(s[2] for s in stock.values()),
            units_available=sum(s[3] for s in stock.values()),
            low_stock_products=low,
            out_of_stock_products=out,
        )

    def orders_overview(self, period: DateRange, *, now: datetime) -> OrdersOverview:
        def count_orders(*conditions: object) -> int:
            return self.db.scalar(select(func.count(Order.id)).where(*conditions)) or 0

        def count_shipments(column: object, start: datetime, end: datetime) -> int:
            return (
                self.db.scalar(select(func.count(Shipment.id)).where(column >= start, column < end))
                or 0
            )

        today_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        return OrdersOverview(
            open=count_orders(Order.status.not_in(_values(NOT_OPEN))),
            backordered=count_orders(Order.status.in_(_values(WAITING_FOR_STOCK))),
            on_hold=count_orders(Order.status == OrderStatus.ON_HOLD.value),
            placed_in_period=count_orders(
                Order.created_at >= period.start, Order.created_at < period.end
            ),
            shipped_in_period=count_shipments(Shipment.shipped_at, period.start, period.end),
            delivered_in_period=count_shipments(Shipment.delivered_at, period.start, period.end),
            shipped_today=count_shipments(
                Shipment.shipped_at, today_start, today_start + timedelta(days=1)
            ),
        )

    def shipments_overview(self) -> ShipmentsOverview:
        def count(*statuses: str) -> int:
            return (
                self.db.scalar(
                    select(func.count(Shipment.id)).where(Shipment.status.in_(list(statuses)))
                )
                or 0
            )

        return ShipmentsOverview(
            on_the_way=count(*_values(ON_THE_WAY)),
            delayed=count(ShipmentStatus.DELAYED.value),
        )

    def alerts_overview(self) -> AlertsOverview:
        unresolved = Alert.status.in_(UNRESOLVED)
        return AlertsOverview(
            unresolved=self.db.scalar(select(func.count(Alert.id)).where(unresolved)) or 0,
            critical=self.db.scalar(
                select(func.count(Alert.id)).where(
                    unresolved, Alert.severity == AlertSeverity.CRITICAL.value
                )
            )
            or 0,
        )

    def purchasing_overview(self, *, today: date) -> PurchasingOverview:
        open_pos = self.db.scalars(
            select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        ).all()
        items = self.db.scalars(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.purchase_order_id.in_([po.id for po in open_pos])
            )
        ).all()
        value = sum((i.unit_cost * i.quantity_outstanding for i in items), Decimal("0"))
        return PurchasingOverview(
            open=len(open_pos),
            overdue=sum(1 for po in open_pos if po.expected_date < today),
            open_value=value.quantize(Decimal("0.01")),
        )


def _where(condition: object, value: object) -> object:
    """`value` where the condition holds, else 0 (for conditional sums)."""
    return case((condition, value), else_=0)
