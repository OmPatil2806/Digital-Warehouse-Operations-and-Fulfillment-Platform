"""Picking and packing, the way the application does it (backend fulfillment_service.py).

Every working day each warehouse works through its fully reserved orders, urgent ones
first, then the oldest. Orders placed after the 14:00 cut-off wait for the next working
day. A warehouse can pick a limited number of order lines per day: in peaks (Black
Friday, December) orders queue up, take longer and are more often delivered late.

For each order (statuses: inventory_reserved -> allocated -> picking -> picked ->
packing -> packed):

1. one picking task per reservation, on a route from the farthest rack to packing;
2. the picker walks the route; a few picks come up short (units missing or damaged):
   the missing units are written off (or marked damaged) by a stock adjustment, the bin
   gets a cycle count, and the units are reserved from another bin if possible (an
   extra task); otherwise the line ships short;
3. a packing task records parcels and weight, then the shipment process takes over.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Any

from app.models import CycleCount, CycleCountLine
from data_generation.context import GenerationContext
from data_generation.generate_orders import PRIORITY_RANK, OrderBook, SimOrder
from data_generation.generate_purchasing import is_working_day, next_working_day
from data_generation.simulation import Simulation, at
from data_generation.stock import Reservation

CUTOFF_HOUR = 14.0  # orders placed later are picked the next working day
SHIFT_START, SHIFT_HOURS = 7.0, 10.0
LINES_PER_ORDER = 2.5
CAPACITY_HEADROOM = 1.3  # picking capacity over the average working day's lines
SHORT_PICK_PROBABILITY = 0.004  # per picking task
SHORT_REASONS = (
    ("decrease", "Units not found in the bin"),
    ("damage", "Damaged units found in the bin"),
)
WALK_SPEED_M_PER_S = 1.2
SECONDS_PER_PICK, SECONDS_PER_UNIT = 15, 4
PARCEL_MAX_KG, PARCEL_MAX_CM3, PACKAGING_KG = 20, 60_000, Decimal("0.25")


class FulfillmentProcess:
    def __init__(self, ctx: GenerationContext, book: OrderBook, shipping: Any) -> None:
        self.ctx = ctx
        self.book = book
        self.shipping = shipping
        self.rng = ctx.rng("fulfillment")
        self.capacity: dict[int, float] = {}
        self.open_counts: dict[int, dict[str, Any]] = {}  # bin -> open cycle count
        self._counts_to_close: dict[date, list[int]] = {}
        self._counts: list[dict[str, Any]] = []
        self._count_lines: list[dict[str, Any]] = []
        self._count_ids = 0
        self._packing_ids = 0
        self.short_picks = 0

    # -------------------------------------------------------------------- hooks
    def on_start(self, sim: Simulation) -> None:
        self.book.before_write = sim.ledger.flush_reservations
        lines_per_day = self.ctx.config.orders_per_day * LINES_PER_ORDER * 7 / 5
        for warehouse_id, share in zip(self.ctx.warehouse_ids, sim.warehouse_shares, strict=True):
            self.capacity[warehouse_id] = max(5.0, lines_per_day * share * CAPACITY_HEADROOM)

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        self._close_counts(day)
        if not is_working_day(day):
            return
        cutoff = at(day, CUTOFF_HOUR)
        ready = sorted(
            (
                o
                for o in self.book.open.values()
                if o.status == "inventory_reserved" and o.created < cutoff
            ),
            key=lambda o: (PRIORITY_RANK[o.priority], o.created, o.id),
        )
        used = dict.fromkeys(self.ctx.warehouse_ids, 0.0)
        for order in ready:
            warehouse_id = order.warehouse_id
            capacity = self.capacity[warehouse_id]
            if used[warehouse_id] >= capacity:
                continue  # waits for the next working day
            start = at(day, SHIFT_START + SHIFT_HOURS * used[warehouse_id] / capacity)
            # Never before the order was ready (e.g. its stock arrived at noon).
            start = max(
                start, order.created + timedelta(minutes=30), order.updated + timedelta(minutes=15)
            )
            used[warehouse_id] += len(order.lines)
            self.fulfil(sim, order, start)

    def on_finish(self, sim: Simulation) -> None:
        self._write_counts()  # finished ones; open counts stay open
        for count in self.open_counts.values():
            self._counts.append(count["row"])
            self._count_lines.extend(count["lines"])
        self._write_counts()

    # ------------------------------------------------------------------ picking
    def fulfil(self, sim: Simulation, order: SimOrder, start: datetime) -> None:
        ledger = sim.ledger
        reservations = [
            ledger.reservations[r] for r in order.reservation_ids if r in ledger.reservations
        ]
        tasks = self._tasks(order, reservations, first_sequence=1, when=start)
        self.book.transition(order, "allocated", start, f"{len(tasks)} picking task(s) created")
        when = start + timedelta(minutes=float(self.rng.uniform(2, 10)))
        self.book.transition(order, "picking", when)
        lines = {line.product_id: line for line in order.lines}
        position = 0.0  # metres from packing
        index = 0
        while index < len(tasks):  # short picks can add tasks to the route
            task = tasks[index]
            distance = sim.ledger.bins[task["bin_id"]].distance_m
            walk = abs(distance - position) + 3
            position = distance
            task["started_at"] = when
            seconds = walk / WALK_SPEED_M_PER_S + SECONDS_PER_PICK
            seconds += SECONDS_PER_UNIT * task["quantity"]
            when += timedelta(seconds=seconds)
            short = 0
            if self.rng.random() < SHORT_PICK_PROBABILITY:
                short = min(task["quantity"], int(self.rng.geometric(0.7)))
            picked = task["quantity"] - short
            ledger.pick(
                task["reservation_id"],
                picked,
                when,
                reason=f"Order {order.number}",
                reference=("order", order.id),
            )
            line = lines[task["product_id"]]
            line.reserved -= task["quantity"]
            line.picked += picked
            task.update(
                quantity_picked=picked,
                status="short" if short else "completed",
                completed_at=when,
                updated_at=when,
            )
            if short:
                self._short_pick(sim, order, task, short, when, tasks)
            index += 1
        when += timedelta(seconds=position / WALK_SPEED_M_PER_S)  # back to packing
        missing = sum(line.quantity - line.picked for line in order.lines)
        note = "All units picked" if not missing else f"Picked with {missing} unit(s) short"
        self.book.transition(order, "picked", when, note)
        if any(line.picked for line in order.lines):
            self._pack(sim, order, when)

    def _tasks(
        self,
        order: SimOrder,
        reservations: list[Reservation],
        *,
        first_sequence: int,
        when: datetime,
    ) -> list[dict[str, Any]]:
        """One task per reservation on the route: farthest racks first, low shelves first."""
        bins = self.ctx.bins
        lines = {line.product_id: line for line in order.lines}

        def route(r: Reservation) -> tuple:
            b = bins[r.bin_id - 1]
            return (-b.distance_m, b.level, b.id)

        tasks = []
        for sequence, reservation in enumerate(sorted(reservations, key=route), first_sequence):
            task = {
                "order_id": order.id,
                "order_item_id": lines[reservation.product_id].id,
                "reservation_id": reservation.id,
                "product_id": reservation.product_id,
                "bin_id": reservation.bin_id,
                "quantity": reservation.quantity,
                "quantity_picked": None,
                "sequence": sequence,
                "status": "pending",
                "assigned_to_id": None,
                "started_at": None,
                "completed_at": None,
                "short_reason": None,
                "created_at": when,
                "updated_at": when,
            }
            tasks.append(task)
            order.picking_tasks.append(task)
        return tasks

    def _short_pick(
        self,
        sim: Simulation,
        order: SimOrder,
        task: dict[str, Any],
        short: int,
        when: datetime,
        tasks: list[dict[str, Any]],
    ) -> None:
        self.short_picks += 1
        ledger = sim.ledger
        kind, text = SHORT_REASONS[int(self.rng.integers(len(SHORT_REASONS)))]
        task["short_reason"] = text
        reason = f"Short pick on order {order.number}: {text}"
        product_id, bin_id = task["product_id"], task["bin_id"]
        # 1. The units are not there (or not sellable): correct the system stock, at most
        #    what other orders have not reserved.
        write_off = min(short, ledger.rows[(product_id, bin_id)].available)
        if write_off:
            ledger.adjust(product_id, bin_id, kind, write_off, when, reason=reason)
        # 2. A second person counts the bin on the next working day.
        if bin_id not in self.open_counts:
            self._open_count(sim, bin_id, when, reason)
        # 3. Reserve the missing units from another bin, as an extra task on the route.
        made = ledger.reserve(
            product_id,
            order.warehouse_id,
            short,
            when,
            order_id=order.id,
            reason=f"Order {order.number} (replaces short pick)",
        )
        line = next(line for line in order.lines if line.product_id == product_id)
        line.reserved += sum(r.quantity for r in made)
        order.reservation_ids.extend(r.id for r in made)
        tasks.extend(self._tasks(order, made, first_sequence=len(tasks) + 1, when=when))

    # ----------------------------------------------------------------- packing
    def _pack(self, sim: Simulation, order: SimOrder, picked_at: datetime) -> None:
        products = sim.ledger.products
        units = sum(line.picked for line in order.lines)
        weight = sum(
            (products[line.product_id].weight_kg * line.picked for line in order.lines),
            Decimal(0),
        )
        volume = sum(products[line.product_id].volume_cm3 * line.picked for line in order.lines)
        parcels = max(1, ceil(weight / PARCEL_MAX_KG), ceil(volume / PARCEL_MAX_CM3))
        weight = (weight + PACKAGING_KG * parcels).quantize(Decimal("0.001"))
        started = picked_at + timedelta(minutes=float(self.rng.uniform(5, 45)))
        packed = started + timedelta(minutes=2 + 0.5 * units + float(self.rng.uniform(0, 3)))
        self.book.transition(order, "packing", started)
        for line in order.lines:
            line.packed = line.picked
        self.book.transition(order, "packed", packed, f"{parcels} parcel(s), {weight} kg")
        self._packing_ids += 1
        order.packing = {
            "id": self._packing_ids,
            "order_id": order.id,
            "status": "completed",
            "packed_by_id": None,
            "started_at": started,
            "completed_at": packed,
            "package_count": parcels,
            "weight_kg": weight,
            "note": None,
            "created_at": picked_at,
            "updated_at": packed,
        }
        self.shipping.ship(sim, order, packed, parcels=parcels, weight_kg=weight)

    # ----------------------------------------------------------- cycle counts
    def _open_count(self, sim: Simulation, bin_id: int, when: datetime, note: str) -> None:
        self._count_ids += 1
        count_id = self._count_ids
        lines = [
            {
                "cycle_count_id": count_id,
                "product_id": product_id,
                "expected_quantity": on_hand,
                "counted_quantity": None,
            }
            for product_id, on_hand in sim.ledger.stock_in_bin(bin_id)
        ]
        self.open_counts[bin_id] = {
            "row": {
                "id": count_id,
                "bin_id": bin_id,
                "status": "open",
                "note": note[:255],
                "submitted_at": None,
                "requested_by_id": None,
                "decided_by_id": None,
                "decided_at": None,
                "decision_note": None,
                "created_at": when,
                "updated_at": when,
            },
            "lines": lines,
        }
        close = next_working_day(when.date() + timedelta(days=1))
        self._counts_to_close.setdefault(close, []).append(bin_id)

    def _close_counts(self, day: date) -> None:
        """The count confirms the corrected stock: no further differences."""
        for bin_id in self._counts_to_close.pop(day, []):
            count = self.open_counts.pop(bin_id)
            counted = at(day, 10.0 + float(self.rng.uniform(0, 4)))
            for line in count["lines"]:
                line["counted_quantity"] = line["expected_quantity"]
            count["row"].update(
                status="completed",
                submitted_at=counted,
                decided_at=counted + timedelta(minutes=30),
                decision_note="No differences",
                updated_at=counted + timedelta(minutes=30),
            )
            self._counts.append(count["row"])
            self._count_lines.extend(count["lines"])
        if len(self._counts) >= self.ctx.config.batch_size:
            self._write_counts()

    def _write_counts(self) -> None:
        if self._counts:
            self.ctx.writer.insert(CycleCount.__table__, self._counts)
            self.ctx.writer.insert(CycleCountLine.__table__, self._count_lines)
            self._counts, self._count_lines = [], []


class HousekeepingProcess:
    """Weekly warehouse housekeeping (Fridays, 15:00), so the returns zone and damaged
    goods do not fill the warehouse over two years:

    - damaged units are written off (disposed of),
    - good units in the returns zone go back to the product's normal storage bins.
    """

    WEEKDAY = 4  # Friday

    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.written_off = 0
        self.moved = 0

    def on_start(self, sim: Simulation) -> None:
        pass

    def on_finish(self, sim: Simulation) -> None:
        pass

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        if day.weekday() != self.WEEKDAY or not is_working_day(day):
            return
        ledger = sim.ledger
        when = at(day, 15.0)
        for bin_id in sorted(ledger.bin_products):
            returns_zone = ledger.bins[bin_id].zone_type == "returns"
            for product_id in sorted(ledger.bin_products[bin_id]):
                row = ledger.rows[(product_id, bin_id)]
                if row.damaged:
                    self.written_off += row.damaged
                    ledger.adjust(
                        product_id,
                        bin_id,
                        "write_off",
                        row.damaged,
                        when,
                        reason="Weekly disposal of damaged goods",
                    )
                if returns_zone and row.available:
                    self.moved += ledger.move_to_storage(
                        product_id, bin_id, when, reason="Returned goods back to storage"
                    )
