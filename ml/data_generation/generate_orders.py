"""Customer orders: placed, confirmed, reserved or backordered, sometimes cancelled.

Every day the demand patterns decide how much of each product customers want
(patterns.demand_rate). The number of orders follows from that (about 4 units per
order), and each order's lines are products drawn in proportion to today's demand:

- about 2.4 lines and 4 units per order; a few business orders buy in bulk,
- basket rules add companion products (a laptop often comes with accessories),
- customers are drawn by activity, so a few large accounts order very often,
- products on promotion sell at 15 % off.

Orders then follow the application's rules (backend order_service.py and
allocation_service.py): confirmed straight away, stock reserved from one warehouse
(the customer's home warehouse when it has everything, else the one covering the most),
picking zones first. Missing units leave the order partially allocated or backordered;
waiting orders are retried every day after deliveries, urgent ones first, then the
oldest. Some customers cancel, more often when they have been waiting a long time.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import numpy as np

from app.models import Order, OrderItem, OrderStatusHistory
from app.services.order_service import can_transition
from data_generation.context import CustomerInfo, GenerationContext
from data_generation.patterns import (
    INTERMITTENT_SALE_DAY_PROBABILITY,
    UNITS_PER_ORDER,
    demand_rate,
    make_basket_rules,
    sample_companions,
)
from data_generation.simulation import Simulation, at

PROMOTION_DISCOUNT = Decimal("0.85")
EXTRA_LINES_MEAN = 1.2  # lines per order = 1 + Poisson(1.2), plus companions
# Units per line: mostly 1-2, sometimes a few more, rarely bulk.
LINE_SIZES = ((1, 1, 0.65), (2, 2, 0.22), (3, 4, 0.10), (5, 12, 0.03))
# When customers order (UTC hour of day): office hours and evenings.
HOUR_WEIGHTS = np.array(
    [1, 1, 1, 1, 1, 2, 4, 7, 10, 12, 12, 11, 10, 11, 12, 11, 10, 9, 8, 8, 7, 5, 3, 2],
    dtype=float,
)
PRIORITIES = {  # customer type -> (priority, probability)
    "business": (("urgent", 0.04), ("high", 0.12), ("normal", 0.80), ("low", 0.04)),
    "consumer": (("urgent", 0.01), ("high", 0.04), ("normal", 0.95)),
}
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
WAITING = ("partially_allocated", "backordered")
CANCEL_AT_ONCE = 0.01  # customers who change their mind right after ordering
PATIENCE_DAYS = 7  # after a week of waiting for stock ...
CANCEL_WHEN_WAITING = 0.05  # ... this share of waiting orders is cancelled every day
REQUESTED_DATE_SHARE = 0.2  # business orders with a requested delivery date


@dataclass(slots=True)
class SimLine:
    line_number: int
    product_id: int
    quantity: int
    unit_price: Decimal
    reserved: int = 0
    picked: int = 0
    packed: int = 0
    shipped: int = 0
    returned: int = 0

    @property
    def missing(self) -> int:
        return self.quantity - self.reserved


@dataclass(slots=True)
class SimOrder:
    id: int
    number: str
    customer: CustomerInfo
    priority: str
    created: datetime
    lines: list[SimLine]
    requested_delivery_date: date | None = None
    warehouse_id: int | None = None
    status: str = "created"
    history: list[tuple[str | None, str, datetime, str | None]] = field(default_factory=list)
    updated: datetime | None = None
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    reservation_ids: list[int] = field(default_factory=list)
    waiting_since: date | None = None

    @property
    def units(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def subtotal(self) -> Decimal:
        return sum((line.unit_price * line.quantity for line in self.lines), Decimal("0.00"))


MILESTONES = {
    "confirmed": "confirmed_at",
    "shipped": "shipped_at",
    "delivered": "delivered_at",
    "cancelled": "cancelled_at",
}


class OrderBook:
    """Open orders in memory; finished ones are written to the database in batches."""

    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.open: dict[int, SimOrder] = {}
        self._finished: list[SimOrder] = []
        self._sequence: dict[int, int] = {}
        self.count = 0

    def new_order(
        self,
        customer: CustomerInfo,
        lines: list[SimLine],
        when: datetime,
        *,
        priority: str,
        requested: date | None,
    ) -> SimOrder:
        self.count += 1
        sequence = self._sequence.get(when.year, 0) + 1
        self._sequence[when.year] = sequence
        order = SimOrder(
            id=self.count,
            number=f"SO-{when.year}-{sequence:06d}",
            customer=customer,
            priority=priority,
            created=when,
            lines=lines,
            requested_delivery_date=requested,
            updated=when,
        )
        order.history.append((None, "created", when, None))
        self.open[order.id] = order
        return order

    def transition(
        self, order: SimOrder, target: str, when: datetime, note: str | None = None
    ) -> None:
        """Change the status like the application does (invalid changes are a bug)."""
        if not can_transition(order.status, target):
            raise AssertionError(f"{order.number}: {order.status} -> {target} is not allowed")
        order.history.append((order.status, target, when, note))
        order.status = target
        order.updated = when
        if target in MILESTONES:
            setattr(order, MILESTONES[target], when)

    def waiting(self) -> list[SimOrder]:
        """Orders waiting for stock: urgent first, then the oldest."""
        return sorted(
            (o for o in self.open.values() if o.status in WAITING),
            key=lambda o: (PRIORITY_RANK[o.priority], o.created, o.id),
        )

    def close(self, order: SimOrder) -> None:
        """The order is finished (delivered, returned or cancelled): write it soon."""
        del self.open[order.id]
        self._finished.append(order)
        if len(self._finished) >= self.ctx.config.batch_size:
            self.flush()

    def flush(self) -> None:
        if self._finished:
            self._write(self._finished)
            self._finished = []

    def finish(self) -> None:
        self.flush()
        self._write(sorted(self.open.values(), key=lambda o: o.id))

    def _write(self, orders: list[SimOrder]) -> None:
        writer = self.ctx.writer
        writer.insert(Order.__table__, (self._order_row(o) for o in orders))
        writer.insert(OrderItem.__table__, (row for o in orders for row in self._item_rows(o)))
        writer.insert(
            OrderStatusHistory.__table__,
            (
                {
                    "order_id": o.id,
                    "from_status": before,
                    "to_status": after,
                    "note": note,
                    "changed_by_id": None,
                    "created_at": when,
                }
                for o in orders
                for before, after, when, note in o.history
            ),
        )

    @staticmethod
    def _order_row(o: SimOrder) -> dict[str, Any]:
        c = o.customer
        return {
            "id": o.id,
            "order_number": o.number,
            "customer_id": c.id,
            "warehouse_id": o.warehouse_id,
            "status": o.status,
            "priority": o.priority,
            "requested_delivery_date": o.requested_delivery_date,
            "ship_to_name": c.name,
            "ship_to_address": c.address_line,
            "ship_to_postal_code": c.postal_code,
            "ship_to_city": c.city,
            "ship_to_country": c.country,
            "notes": None,
            "subtotal": o.subtotal,
            "created_by_id": None,
            "confirmed_at": o.confirmed_at,
            "shipped_at": o.shipped_at,
            "delivered_at": o.delivered_at,
            "cancelled_at": o.cancelled_at,
            "cancel_reason": o.cancel_reason,
            "status_before_hold": None,
            "created_at": o.created,
            "updated_at": o.updated,
        }

    @staticmethod
    def _item_rows(o: SimOrder) -> Iterator[dict[str, Any]]:
        for line in o.lines:
            yield {
                "order_id": o.id,
                "line_number": line.line_number,
                "product_id": line.product_id,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "quantity_reserved": line.reserved,
                "quantity_picked": line.picked,
                "quantity_packed": line.packed,
                "quantity_shipped": line.shipped,
                "quantity_returned": line.returned,
            }


class OrdersProcess:
    def __init__(self, ctx: GenerationContext, book: OrderBook) -> None:
        self.ctx = ctx
        self.book = book
        self.rng = ctx.rng("orders")
        self.products = ctx.products
        self.home: dict[int, int] = {}
        self.basket_rules: dict[int, tuple[int, ...]] = {}
        weights = np.array([c.activity for c in ctx.customers])
        self.customer_p = weights / weights.sum()
        self.hour_p = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

    # -------------------------------------------------------------------- hooks
    def on_start(self, sim: Simulation) -> None:
        shares = sim.warehouse_shares
        homes = self.rng.choice(self.ctx.warehouse_ids, size=len(self.ctx.customers), p=shares)
        self.home = {c.id: int(w) for c, w in zip(self.ctx.customers, homes, strict=True)}
        self.basket_rules = make_basket_rules(self.rng, [p.category for p in self.products])

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        self._retry_waiting(sim, day)
        self._cancel_impatient(sim, day)
        for order in self._new_orders(day, day_index):
            self._place(sim, order, day_index)

    def on_finish(self, sim: Simulation) -> None:
        pass  # the order book is written by the generator after all processes

    # --------------------------------------------------------------- new orders
    def _line_size(self) -> int:
        roll = self.rng.random()
        for low, high, probability in LINE_SIZES:
            if roll < probability:
                return int(self.rng.integers(low, high + 1))
            roll -= probability
        return 1

    def _new_orders(self, day: date, day_index: int) -> list[SimOrder]:
        # 1. How much each product sells today. Intermittent products sell on few days
        #    only, but then a lot (same average).
        weights = np.zeros(len(self.products))
        for index, product in enumerate(self.products):
            rate = demand_rate(product.profile, day, day_index, self.ctx.config.days)
            on_sale_day = self.rng.random() < INTERMITTENT_SALE_DAY_PROBABILITY
            if product.profile.intermittent and not on_sale_day:
                continue
            weights[index] = rate
        expected_units = float(weights.sum())
        if expected_units <= 0:
            return []
        count = int(self.rng.poisson(expected_units / UNITS_PER_ORDER))
        if count == 0:
            return []

        # 2. Lines: products drawn in proportion to today's demand, plus companions
        #    from the basket rules.
        p = weights / expected_units
        line_counts = 1 + self.rng.poisson(EXTRA_LINES_MEAN, size=count)
        drawn = iter(self.rng.choice(len(self.products), size=int(line_counts.sum()), p=p))
        groups: list[dict[int, int]] = []
        for lines_wanted in line_counts:
            anchor = int(next(drawn))
            lines = {anchor: self._line_size()}
            for companion in sample_companions(self.rng, anchor, self.basket_rules):
                lines.setdefault(companion, self._line_size())
            for _ in range(int(lines_wanted) - 1):
                index = int(next(drawn))
                if len(lines) >= lines_wanted and index not in lines:
                    continue  # companions already filled this order
                lines[index] = lines.get(index, 0) + self._line_size()
            groups.append(lines)

        # 3. Customers, times, priorities and prices.
        hours = np.sort(self.rng.choice(24, size=len(groups), p=self.hour_p))
        customers = self.rng.choice(len(self.ctx.customers), size=len(groups), p=self.customer_p)
        orders = []
        for lines, hour, customer_index in zip(groups, hours, customers, strict=True):
            customer = self.ctx.customers[int(customer_index)]
            when = at(day, float(hour) + float(self.rng.random()))
            order_lines = []
            for number, (index, units) in enumerate(lines.items(), start=1):
                product = self.products[index]
                price = product.unit_price
                if product.profile.promotion_factor(day) > 1:
                    price = (price * PROMOTION_DISCOUNT).quantize(Decimal("0.01"))
                order_lines.append(SimLine(number, product.id, units, price))
            priorities, weights = zip(*PRIORITIES[customer.customer_type], strict=True)
            priority = str(self.rng.choice(priorities, p=weights))
            requested = None
            if customer.customer_type == "business" and self.rng.random() < REQUESTED_DATE_SHARE:
                requested = day + timedelta(days=int(self.rng.integers(3, 11)))
            orders.append(
                self.book.new_order(
                    customer, order_lines, when, priority=priority, requested=requested
                )
            )
        return orders

    # ---------------------------------------------------------------- lifecycle
    def _place(self, sim: Simulation, order: SimOrder, day_index: int) -> None:
        confirmed = order.created + timedelta(minutes=float(self.rng.uniform(1, 30)))
        self.book.transition(order, "confirmed", confirmed)
        self.reserve(sim, order, confirmed)
        serving = order.warehouse_id or self.home[order.customer.id]
        for line in order.lines:
            sim.demand.record(line.product_id, serving, line.quantity, day_index)
        if self.rng.random() < CANCEL_AT_ONCE:
            later = confirmed + timedelta(hours=float(self.rng.uniform(0.5, 4)))
            self.cancel(sim, order, later, "Customer changed their mind")

    def choose_warehouse(self, sim: Simulation, order: SimOrder) -> int | None:
        """The warehouse covering the most missing units; ties go to the customer's home
        warehouse, then the lowest id (so home wins whenever it has everything). None
        when no warehouse has any of it."""
        home = self.home[order.customer.id]
        coverage = {}
        for warehouse_id in self.ctx.warehouse_ids:
            coverage[warehouse_id] = sum(
                min(line.missing, sim.ledger.available(line.product_id, warehouse_id))
                for line in order.lines
            )
        best = max(coverage.values())
        if best == 0:
            return None
        return min(
            (w for w, units in coverage.items() if units == best),
            key=lambda w: (w != home, w),
        )

    def reserve(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        """Reserve what is available for the missing units and set the status."""
        if order.warehouse_id is None:
            order.warehouse_id = self.choose_warehouse(sim, order)
        if order.warehouse_id is not None:
            for line in order.lines:
                if line.missing == 0:
                    continue
                made = sim.ledger.reserve(
                    line.product_id,
                    order.warehouse_id,
                    line.missing,
                    when,
                    order_id=order.id,
                    reason=f"Order {order.number}",
                )
                line.reserved += sum(r.quantity for r in made)
                order.reservation_ids.extend(r.id for r in made)
        if all(line.missing == 0 for line in order.lines):
            target = "inventory_reserved"
        elif any(line.reserved for line in order.lines):
            target = "partially_allocated"
        else:
            target = "backordered"
        if target != order.status:
            reserved = sum(line.reserved for line in order.lines)
            self.book.transition(order, target, when, f"{reserved} of {order.units} units reserved")
        if target in WAITING and order.waiting_since is None:
            order.waiting_since = when.date()

    def cancel(self, sim: Simulation, order: SimOrder, when: datetime, reason: str) -> None:
        for reservation_id in order.reservation_ids:
            if reservation_id in sim.ledger.reservations:
                sim.ledger.release(reservation_id, when, reason=f"Order {order.number} cancelled")
        for line in order.lines:
            line.reserved = 0
        self.book.transition(order, "cancelled", when, reason)
        order.cancel_reason = reason
        self.book.close(order)

    def _retry_waiting(self, sim: Simulation, day: date) -> None:
        when = at(day, 12.5)  # after the morning deliveries
        for order in self.book.waiting():
            self.reserve(sim, order, when)

    def _cancel_impatient(self, sim: Simulation, day: date) -> None:
        for order in self.book.waiting():
            waited = (day - order.waiting_since).days if order.waiting_since else 0
            if waited >= PATIENCE_DAYS and self.rng.random() < CANCEL_WHEN_WAITING:
                when = at(day, 9.0 + float(self.rng.uniform(0, 8)))
                self.cancel(sim, order, when, f"Customer cancelled after waiting {waited} days")
