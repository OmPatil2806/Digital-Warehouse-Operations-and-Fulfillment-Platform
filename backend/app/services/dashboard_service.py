"""KPI aggregation for the dashboards (project document, section 9.4).

All numbers are computed from the operational tables, so they always agree with the
rest of the application:

- *Stock* KPIs (inventory, open orders, shipments on the way, alerts, open purchase
  orders) describe the warehouse **now**.
- *Period* KPIs (orders placed, shipped, delivered; units picked, turnover, days of
  supply) count events inside the chosen date range. Both days are included; days are
  UTC days.

Sums of money are calculated per product in Python from exact `Decimal` prices, never
with floating point.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.exceptions import UnprocessableError
from app.models.audit import Alert, AlertSeverity
from app.models.catalog import Product
from app.models.inventory import Inventory, InventoryMovement, MovementType
from app.models.order import Order, OrderStatus
from app.models.purchase import OPEN_PO_STATUSES, PurchaseOrder, PurchaseOrderItem
from app.models.shipment import Shipment, ShipmentStatus
from app.models.warehouse import Bin
from app.schemas.dashboard import (
    AlertsOverview,
    CategoryStock,
    InventoryDashboard,
    InventoryOverview,
    InventoryTotals,
    OrdersOverview,
    OverviewDashboard,
    Period,
    ProductStockKpi,
    PurchasingOverview,
    ShipmentsOverview,
    StockStatusCounts,
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
class StockRow:
    on_hand: int
    reserved: int
    damaged: int
    available: int  # in active bins only


EMPTY_STOCK = StockRow(0, 0, 0, 0)


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
        stock = self._stock_by_product()
        value = Decimal("0")
        low = out = 0
        for product in self.db.scalars(select(Product)).all():
            row = stock.get(product.id, EMPTY_STOCK)
            value += product.unit_cost * row.on_hand
            if not product.is_active:
                continue
            if row.available == 0:
                out += 1
            if row.available < product.min_stock:  # min_stock 0 never counts
                low += 1
        return InventoryOverview(
            value_at_cost=_money(value),
            units_on_hand=sum(r.on_hand for r in stock.values()),
            units_reserved=sum(r.reserved for r in stock.values()),
            units_damaged=sum(r.damaged for r in stock.values()),
            units_available=sum(r.available for r in stock.values()),
            low_stock_products=low,
            out_of_stock_products=out,
        )

    def _stock_by_product(self) -> dict[int, "StockRow"]:
        """Current units per product, summed over its bins."""
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
        return {
            pid: StockRow(int(oh), int(rs), int(dm), int(av or 0)) for pid, oh, rs, dm, av in rows
        }

    # -------------------------------------------------------------- inventory
    def inventory(
        self,
        period: DateRange,
        *,
        include_financials: bool,
        limit: int = 100,
    ) -> InventoryDashboard:
        """Stock value, status per product and category, turnover and days of supply.

        Turnover and days of supply use the units *picked* for orders in the period
        (customer demand); receipts, transfers and corrections are not demand.
        Average stock = (on hand at the start + on hand at the end of the period) / 2,
        where earlier stock is rebuilt from the movements since then.
        """
        stock = self._stock_by_product()
        picked = self._units_picked(period)
        on_hand_start = self._on_hand_at(period.start, stock)
        on_hand_end = self._on_hand_at(period.end, stock)  # no movements lie ahead
        days = Decimal(period.days)

        totals = {"cost": Decimal("0"), "price": Decimal("0"), "picked_cost": Decimal("0")}
        avg_value = available_value = Decimal("0")
        status_counts = {"ok": 0, "low": 0, "out": 0}
        categories: dict[int, CategoryStock] = {}
        product_rows: list[ProductStockKpi] = []
        products = self.db.scalars(select(Product).order_by(Product.sku)).all()
        for product in products:
            row = stock.get(product.id, EMPTY_STOCK)
            units_picked = picked.get(product.id, 0)
            cost = product.unit_cost * row.on_hand
            price = product.unit_price * row.on_hand
            totals["cost"] += cost
            totals["price"] += price
            totals["picked_cost"] += product.unit_cost * units_picked
            average = Decimal(on_hand_start.get(product.id, 0) + on_hand_end.get(product.id, 0))
            average /= 2
            avg_value += product.unit_cost * average
            available_value += product.unit_cost * row.available

            category = categories.setdefault(
                product.category_id,
                CategoryStock(
                    category_id=product.category_id,
                    category=product.category.name,
                    products=0,
                    units_on_hand=0,
                    value_at_cost=Decimal("0"),
                    value_at_price=Decimal("0"),
                ),
            )
            category.products += 1
            category.units_on_hand += row.on_hand
            category.value_at_cost += cost
            category.value_at_price += price

            if not product.is_active:
                continue
            status = stock_status(row.available, product.min_stock)
            status_counts[status] += 1
            daily = Decimal(units_picked) / days
            product_rows.append(
                ProductStockKpi(
                    product_id=product.id,
                    sku=product.sku,
                    name=product.name,
                    category=product.category.name,
                    status=status,
                    min_stock=product.min_stock,
                    units_on_hand=row.on_hand,
                    units_available=row.available,
                    units_picked=units_picked,
                    avg_daily_demand=_ratio(daily),
                    days_of_supply=_ratio(row.available / daily, 1) if daily else None,
                    turnover=_ratio(units_picked / average) if average else None,
                    value_at_cost=_money(cost),
                )
            )

        # Most urgent first: fewest days of supply, then products without demand.
        product_rows.sort(key=lambda p: (p.days_of_supply is None, p.days_of_supply or 0, p.sku))
        by_category = sorted(categories.values(), key=lambda c: (-c.value_at_cost, c.category))
        for category in by_category:
            category.value_at_cost = _money(category.value_at_cost)
            category.value_at_price = _money(category.value_at_price)
        daily_cost = totals["picked_cost"] / days
        result = InventoryDashboard(
            period=period.period(),
            include_financials=include_financials,
            totals=InventoryTotals(
                value_at_cost=_money(totals["cost"]),
                value_at_price=_money(totals["price"]),
                units_on_hand=sum(r.on_hand for r in stock.values()),
                units_available=sum(r.available for r in stock.values()),
                units_reserved=sum(r.reserved for r in stock.values()),
                units_damaged=sum(r.damaged for r in stock.values()),
                units_picked=sum(picked.values()),
            ),
            turnover=_ratio(totals["picked_cost"] / avg_value) if avg_value else None,
            days_of_supply=_ratio(available_value / daily_cost, 1) if daily_cost else None,
            stock_status=StockStatusCounts(**status_counts),
            by_category=by_category,
            products=product_rows[:limit],
            products_total=len(product_rows),
        )
        if not include_financials:
            result.totals.value_at_cost = result.totals.value_at_price = None
            for category in result.by_category:
                category.value_at_cost = category.value_at_price = None
            for row in result.products:
                row.value_at_cost = None
        return result

    def _units_picked(self, period: DateRange) -> dict[int, int]:
        rows = self.db.execute(
            select(InventoryMovement.product_id, func.sum(InventoryMovement.on_hand_delta))
            .where(
                InventoryMovement.movement_type == MovementType.PICK.value,
                InventoryMovement.created_at >= period.start,
                InventoryMovement.created_at < period.end,
            )
            .group_by(InventoryMovement.product_id)
        ).all()
        return {pid: -int(delta) for pid, delta in rows if delta}

    def _on_hand_at(self, moment: datetime, stock: dict[int, "StockRow"]) -> dict[int, int]:
        """Units on hand per product at `moment`: today's stock minus later changes."""
        later = dict(
            self.db.execute(
                select(InventoryMovement.product_id, func.sum(InventoryMovement.on_hand_delta))
                .where(InventoryMovement.created_at >= moment)
                .group_by(InventoryMovement.product_id)
            ).all()
        )
        products = set(stock) | set(later)
        return {
            pid: stock.get(pid, EMPTY_STOCK).on_hand - int(later.get(pid) or 0) for pid in products
        }

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
            open_value=_money(value),
        )


def stock_status(available: int, min_stock: int) -> str:
    """ok / low / out for one product (low: below its minimum, but not empty)."""
    if available <= 0:
        return "out"
    return "low" if available < min_stock else "ok"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _ratio(value: Decimal, places: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _where(condition: object, value: object) -> object:
    """`value` where the condition holds, else 0 (for conditional sums)."""
    return case((condition, value), else_=0)
