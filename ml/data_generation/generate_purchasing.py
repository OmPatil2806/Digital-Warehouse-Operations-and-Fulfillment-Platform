"""Opening stock, automatic reordering and supplier deliveries.

The purchasing team follows a simple, common policy, deliberately *not* a perfect one
(the reorder use case of Phase 8 should be able to do better):

- Every working day each product is reviewed per warehouse. Its *position* is the
  available stock plus what is still on order.
- If the position is at or below the reorder point
  ``daily demand x (promised lead time + SAFETY_DAYS)``, it is ordered up to
  ``daily demand x (promised lead time + SAFETY_DAYS + COVER_DAYS)``
  (at least the supplier's minimum order quantity).
- Daily demand is the average of the last four weeks: it ignores seasons, trends and
  promotions, so stock runs short before peaks and after promotions.
- Normally the preferred supplier delivers; when a product is already out of stock and
  a second source promises a shorter lead time, the second source is used.

Deliveries arrive after the supplier's real lead time (patterns.sample_lead_time: late
more often in peak season), only on working days. Some purchase orders arrive in two
parts. If a bin has no room, the rest waits at the dock for the next day.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from math import ceil
from typing import Any

from app.models import PurchaseOrder, PurchaseOrderItem
from data_generation.context import GenerationContext, ProductInfo
from data_generation.patterns import sample_lead_time
from data_generation.simulation import Simulation, at

SAFETY_DAYS = 5
COVER_DAYS = 30
OPENING_FILL = (0.6, 1.0)  # opening stock as a share of the order-up-to level
SPLIT_DELIVERY_SHARE = 0.08  # purchase orders delivered in two parts
PUBLIC_HOLIDAYS = {(1, 1), (12, 25), (12, 26)}


def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and (day.month, day.day) not in PUBLIC_HOLIDAYS


def next_working_day(day: date) -> date:
    while not is_working_day(day):
        day += timedelta(days=1)
    return day


@dataclass
class OrderLine:
    product_id: int
    quantity: int
    unit_cost: Decimal
    received: int = 0


@dataclass
class OpenPurchaseOrder:
    id: int
    number: str
    supplier_id: int
    warehouse_id: int
    ordered: date
    ordered_hour: float
    expected: date
    lines: list[OrderLine] = field(default_factory=list)
    received_on: date | None = None
    received_hour: float = 0.0

    @property
    def complete(self) -> bool:
        return all(line.received == line.quantity for line in self.lines)


class PurchasingProcess:
    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.rng = ctx.rng("purchasing")
        self.orders: list[OpenPurchaseOrder] = []
        self.on_order: dict[tuple[int, int], int] = {}  # (product, warehouse) -> units
        self.deliveries: dict[date, list[tuple[OpenPurchaseOrder, OrderLine, int]]] = {}
        self.suppliers = {s.id: s for s in ctx.suppliers}
        self._sequence: dict[int, int] = {}  # year -> last PO number

    # ------------------------------------------------------------------- policy
    def lead_days(self, supplier_id: int) -> int:
        return self.suppliers[supplier_id].profile.promised_lead_days

    def reorder_point(self, rate: float, lead_days: int) -> float:
        return rate * (lead_days + SAFETY_DAYS)

    def order_up_to(self, rate: float, lead_days: int) -> float:
        return rate * (lead_days + SAFETY_DAYS + COVER_DAYS)

    def choose_supplier(self, product: ProductInfo, available: int) -> int:
        preferred = product.supplier_ids[0]
        if available <= 0 and len(product.supplier_ids) > 1:
            second = product.supplier_ids[1]
            if self.lead_days(second) < self.lead_days(preferred):
                return second
        return preferred

    # -------------------------------------------------------------------- hooks
    def on_start(self, sim: Simulation) -> None:
        """Opening stock on the first morning, from what each warehouse expects to sell."""
        start = self.ctx.config.start_date
        for product in self.ctx.products:
            lead = self.lead_days(product.supplier_ids[0])
            for warehouse_id in self.ctx.warehouse_ids:
                rate = sim.demand.daily_rate(product.id, warehouse_id)
                level = self.order_up_to(rate, lead) * self.rng.uniform(*OPENING_FILL)
                units = max(product.min_order_qty, ceil(level))
                sim.ledger.receive(
                    product.id, warehouse_id, units, at(start, 6.0), reason="Opening stock"
                )

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        self._receive(sim, day)
        if is_working_day(day):
            self._review(sim, day)

    def on_finish(self, sim: Simulation) -> None:
        self.ctx.writer.insert(PurchaseOrder.__table__, self._order_rows())
        self.ctx.writer.insert(PurchaseOrderItem.__table__, self._item_rows())

    # --------------------------------------------------------------- deliveries
    def _receive(self, sim: Simulation, day: date) -> None:
        for order, line, units in self.deliveries.pop(day, []):
            hour = 7.0 + float(self.rng.uniform(0, 5))  # the dock is busy in the morning
            received = sim.ledger.receive(
                line.product_id,
                order.warehouse_id,
                units,
                at(day, hour),
                reason=f"Purchase order {order.number} ({self.suppliers[order.supplier_id].code})",
            )
            line.received += received
            self.on_order[(line.product_id, order.warehouse_id)] -= received
            if received < units:  # no room: the rest waits for the next working day
                later = next_working_day(day + timedelta(days=1))
                self.deliveries.setdefault(later, []).append((order, line, units - received))
            if order.complete:
                order.received_on, order.received_hour = day, hour

    # ------------------------------------------------------------------- review
    def _review(self, sim: Simulation, day: date) -> None:
        new_lines: dict[tuple[int, int], list[OrderLine]] = {}
        for product in self.ctx.products:
            for warehouse_id in self.ctx.warehouse_ids:
                rate = sim.demand.daily_rate(product.id, warehouse_id)
                if rate <= 0:
                    continue
                available = sim.ledger.available(product.id, warehouse_id)
                position = available + self.on_order.get((product.id, warehouse_id), 0)
                supplier_id = self.choose_supplier(product, available)
                lead = self.lead_days(supplier_id)
                if position > self.reorder_point(rate, lead):
                    continue
                units = max(product.min_order_qty, ceil(self.order_up_to(rate, lead) - position))
                new_lines.setdefault((supplier_id, warehouse_id), []).append(
                    OrderLine(product.id, units, product.offer_costs[supplier_id])
                )
                self.on_order[(product.id, warehouse_id)] = (
                    self.on_order.get((product.id, warehouse_id), 0) + units
                )
        for (supplier_id, warehouse_id), lines in new_lines.items():
            self._place(supplier_id, warehouse_id, lines, day)

    def _place(
        self, supplier_id: int, warehouse_id: int, lines: list[OrderLine], day: date
    ) -> None:
        sequence = self._sequence.get(day.year, 0) + 1
        self._sequence[day.year] = sequence
        supplier = self.suppliers[supplier_id]
        order = OpenPurchaseOrder(
            id=len(self.orders) + 1,
            number=f"PO-{day.year}-{sequence:06d}",
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            ordered=day,
            ordered_hour=9.0 + float(self.rng.uniform(0, 7)),
            expected=day + timedelta(days=supplier.profile.promised_lead_days),
            lines=lines,
        )
        self.orders.append(order)
        arrival = next_working_day(
            day + timedelta(days=sample_lead_time(self.rng, supplier.profile, day))
        )
        split = len(lines) > 1 and self.rng.random() < SPLIT_DELIVERY_SHARE
        rest_day = next_working_day(arrival + timedelta(days=int(self.rng.integers(2, 7))))
        for line in lines:
            first = line.quantity
            if split:
                first = max(1, int(line.quantity * self.rng.uniform(0.5, 0.8)))
            self.deliveries.setdefault(arrival, []).append((order, line, first))
            if first < line.quantity:
                self.deliveries.setdefault(rest_day, []).append(
                    (order, line, line.quantity - first)
                )

    # --------------------------------------------------------------------- rows
    def _order_rows(self) -> Iterator[dict[str, Any]]:
        for order in self.orders:
            received_any = any(line.received for line in order.lines)
            if order.complete:
                status = "received"
            elif received_any:
                status = "partially_received"
            else:
                status = "ordered"
            ordered_at = at(order.ordered, order.ordered_hour)
            yield {
                "id": order.id,
                "po_number": order.number,
                "supplier_id": order.supplier_id,
                "warehouse_id": order.warehouse_id,
                "status": status,
                "expected_date": order.expected,
                "notes": None,
                "created_by_id": None,
                "ordered_at": ordered_at,
                "received_at": (
                    at(order.received_on, order.received_hour) if order.received_on else None
                ),
                "created_at": ordered_at,
                "updated_at": (
                    at(order.received_on, order.received_hour) if order.received_on else ordered_at
                ),
            }

    def _item_rows(self) -> Iterator[dict[str, Any]]:
        for order in self.orders:
            for line in order.lines:
                yield {
                    "purchase_order_id": order.id,
                    "product_id": line.product_id,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "quantity_received": line.received,
                }
