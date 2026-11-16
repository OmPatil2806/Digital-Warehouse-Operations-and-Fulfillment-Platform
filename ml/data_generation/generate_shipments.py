"""Shipments, tracking events, delays and returns (backend shipment and return services).

A packed order is handed to a carrier at the 17:30 pick-up (the next working day when
packed later). Urgent orders go by express. The expected delivery date is the carrier's
transit time in working days. Whether the parcel is late comes from the delay model
(patterns.delay_probability), which the delay-prediction use case should learn back:

    large orders, an order that had to wait for stock, a crowded warehouse,
    an unreliable carrier and peak season all make delays more likely.

Tracking: dispatched -> in transit (next morning) -> [delayed, on the expected day] ->
out for delivery -> delivered. A delayed order goes shipped -> delayed -> delivered.

After delivery some lines come back (per-category return rates). The customer opens a
return a few days later; the goods arrive and are inspected into a bin of the returns
zone, some as damaged; the order becomes "returned". A few returns are cancelled.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from data_generation import catalog_data
from data_generation.context import CarrierInfo, GenerationContext
from data_generation.generate_orders import OrderBook, SimOrder
from data_generation.generate_purchasing import is_working_day, next_working_day
from data_generation.patterns import (
    RETURN_DAMAGED_SHARE,
    DelayFactors,
    delay_probability,
    is_peak_season,
    return_probability,
    sample_delay_days,
)
from data_generation.simulation import Simulation, at

PICKUP_HOUR = 17.5
LAST_PACKING_HOUR = 17.0
CARRIER_SHARES = {"DHL": 0.35, "DPD": 0.2, "UPS": 0.15, "GLS": 0.15, "HERMES": 0.1, "FEDEX": 0.05}
EXPRESS = ("UPS", "FEDEX")
EARLY_SHARE = 0.1  # parcels that arrive a day before the expected date
DELAY_REASONS = (
    "High parcel volume at the hub",
    "Vehicle breakdown",
    "Weather conditions",
    "Recipient not at home",
    "Address could not be found",
)
RETURN_REASONS = (
    "Does not fit",
    "Changed my mind",
    "Damaged on arrival",
    "Wrong item delivered",
    "Not as described",
)
DAMAGED_ON_ARRIVAL_SHARE = 0.8  # of "Damaged on arrival" returns that really are
RETURN_CANCEL_SHARE = 0.05


def add_working_days(start: date, days: int) -> date:
    """Like the application: Saturdays and Sundays are skipped."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


class ShipmentsProcess:
    def __init__(self, ctx: GenerationContext, book: OrderBook) -> None:
        self.ctx = ctx
        self.book = book
        self.rng = ctx.rng("shipments")
        self.schedule: dict[date, list[tuple[datetime, int, str, SimOrder]]] = {}
        self._serial = 0
        self._shipment_ids = 0
        self._return_ids = 0
        self._return_sequence: dict[int, int] = {}
        self._occupancy: dict[tuple[date, int], float] = {}
        carriers = ctx.carriers
        self.carriers = {c.code: c for c in carriers}
        codes = [c.code for c in carriers]
        weights = [CARRIER_SHARES.get(code, 0.05) for code in codes]
        total = sum(weights)
        self.carrier_choice = (codes, [w / total for w in weights])
        self.express = [code for code in codes if code in EXPRESS] or codes
        self.warehouse_city = {
            index: address.split(",")[1].split()[-1]
            for index, (_c, _n, address) in enumerate(catalog_data.WAREHOUSES, start=1)
        }
        self.late = 0
        self.delivered = 0
        self.waiting_at_dock = 0  # return inspections postponed for lack of room

    # -------------------------------------------------------------------- hooks
    def on_start(self, sim: Simulation) -> None:
        pass

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        for when, _serial, kind, order in sorted(self.schedule.pop(day, [])):
            getattr(self, f"_on_{kind}")(sim, order, when)

    def on_finish(self, sim: Simulation) -> None:
        pass  # parcels still on their way stay so; open returns stay open

    def _plan(self, when: datetime, kind: str, order: SimOrder) -> None:
        self._serial += 1
        self.schedule.setdefault(when.date(), []).append((when, self._serial, kind, order))

    # ----------------------------------------------------------------- shipping
    def ship(
        self,
        sim: Simulation,
        order: SimOrder,
        packed: datetime,
        *,
        parcels: int,
        weight_kg: Decimal,
    ) -> None:
        day = packed.date()
        if packed > at(day, LAST_PACKING_HOUR) or not is_working_day(day):
            day = next_working_day(day + timedelta(days=1))
        shipped = at(day, PICKUP_HOUR + float(self.rng.uniform(0, 0.4)))
        carrier = self._carrier(order)
        expected = add_working_days(day, carrier.transit_days)
        tracking = f"{carrier.code}{day:%y%m%d}{order.id:06d}"
        factors = DelayFactors(
            units=sum(line.packed for line in order.lines),
            low_stock=order.waiting_since is not None,
            occupancy=self.occupancy(sim, day, order.warehouse_id),
            carrier_reliability=carrier.reliability,
            peak_season=is_peak_season(day),
        )
        late = self.rng.random() < delay_probability(factors)
        if late:
            arrival = add_working_days(expected, sample_delay_days(self.rng))
        elif carrier.transit_days > 1 and self.rng.random() < EARLY_SHARE:
            arrival = add_working_days(day, carrier.transit_days - 1)
        else:
            arrival = expected

        self._shipment_ids += 1
        order.carrier_code = carrier.code
        order.shipment = {
            "id": self._shipment_ids,
            "order_id": order.id,
            "carrier_id": carrier.id,
            "tracking_number": tracking,
            "status": "dispatched",
            "package_count": parcels,
            "weight_kg": weight_kg,
            "shipped_at": shipped,
            "expected_delivery_date": expected,
            "delivered_at": None,
            "created_by_id": None,
            "created_at": shipped,
            "updated_at": shipped,
        }
        for line in order.lines:
            line.shipped = line.packed
        self.book.transition(
            order, "shipped", shipped, f"{carrier.code} {tracking}, expected {expected.isoformat()}"
        )
        city = self.warehouse_city.get(order.warehouse_id, "")
        self._event(order, "dispatched", shipped, f"Warehouse {city}", f"Handed to {carrier.name}")
        self._plan(
            at(day + timedelta(days=1), 6.0 + float(self.rng.uniform(0, 3))), "transit", order
        )
        if late:
            self._plan(at(expected, 19.0), "delay", order)
        self._plan(at(arrival, 7.5 + float(self.rng.uniform(0, 1))), "out_for_delivery", order)
        self._plan(at(arrival, 10.0 + float(self.rng.uniform(0, 8))), "delivery", order)

    def _carrier(self, order: SimOrder) -> CarrierInfo:
        if order.priority == "urgent":
            code = self.express[int(self.rng.integers(len(self.express)))]
        else:
            codes, weights = self.carrier_choice
            code = str(self.rng.choice(codes, p=weights))
        return self.carriers[code]

    def occupancy(self, sim: Simulation, day: date, warehouse_id: int) -> float:
        key = (day, warehouse_id)
        if key not in self._occupancy:
            self._occupancy[key] = sim.ledger.occupancy(warehouse_id)
        return self._occupancy[key]

    def _event(
        self,
        order: SimOrder,
        event_type: str,
        when: datetime,
        location: str | None,
        description: str | None = None,
    ) -> None:
        order.events.append(
            {
                "shipment_id": order.shipment["id"],
                "event_type": event_type,
                "occurred_at": when,
                "location": location,
                "description": description,
                "created_by_id": None,
                "created_at": when,
            }
        )
        order.shipment["updated_at"] = when

    # ------------------------------------------------------------------ tracking
    def _on_transit(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        carrier = order.carrier_code
        city = self.warehouse_city.get(order.warehouse_id, "")
        self._event(order, "in_transit", when, f"{carrier} hub {city}")
        if order.shipment["status"] == "dispatched":
            order.shipment["status"] = "in_transit"

    def _on_delay(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        reason = DELAY_REASONS[int(self.rng.integers(len(DELAY_REASONS)))]
        self._event(order, "delayed", when, None, reason)
        order.shipment["status"] = "delayed"
        if order.status == "shipped":
            self.book.transition(order, "delayed", when, reason)
        self.late += 1

    def _on_out_for_delivery(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        self._event(order, "out_for_delivery", when, order.customer.city)
        if order.shipment["status"] == "dispatched":
            order.shipment["status"] = "in_transit"

    def _on_delivery(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        self._event(order, "delivered", when, order.customer.city)
        order.shipment.update(status="delivered", delivered_at=when)
        self.book.transition(order, "delivered", when, order.customer.city)
        self.delivered += 1
        self._decide_return(sim, order, when)

    # ------------------------------------------------------------------- returns
    def _decide_return(self, sim: Simulation, order: SimOrder, delivered: datetime) -> None:
        products = sim.ledger.products
        lines = []
        for line in order.lines:
            category = products[line.product_id].category
            if line.shipped and self.rng.random() < return_probability(category):
                quantity = 1 if line.shipped == 1 else int(self.rng.integers(1, line.shipped + 1))
                lines.append((line, quantity))
        if not lines:
            self.book.close(order)
            return
        opened = delivered + timedelta(
            days=int(self.rng.integers(2, 21)), hours=float(self.rng.uniform(-3, 3))
        )
        order.pending_return = lines
        self._plan(opened, "return_opened", order)

    def _on_return_opened(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        pending = order.pending_return
        self._return_ids += 1
        sequence = self._return_sequence.get(when.year, 0) + 1
        self._return_sequence[when.year] = sequence
        reason = RETURN_REASONS[int(self.rng.integers(len(RETURN_REASONS)))]
        ret = {
            "id": self._return_ids,
            "return_number": f"RT-{when.year}-{sequence:06d}",
            "order_id": order.id,
            "status": "open",
            "reason": reason,
            "created_by_id": None,
            "inspected_by_id": None,
            "completed_at": None,
            "created_at": when,
            "updated_at": when,
            "items": [
                {
                    "return_id": self._return_ids,
                    "order_item_id": line.id,
                    "quantity": quantity,
                    "condition": None,
                    "bin_id": None,
                    "note": None,
                }
                for line, quantity in pending
            ],
        }
        order.returns.append(ret)
        later = when + timedelta(days=int(self.rng.integers(3, 11)))
        kind = "return_cancelled" if self.rng.random() < RETURN_CANCEL_SHARE else "return_inspected"
        self._plan(at(later.date(), 9.0 + float(self.rng.uniform(0, 7))), kind, order)

    def _on_return_cancelled(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        ret = order.returns[-1]
        ret.update(status="cancelled", updated_at=when)
        self.book.close(order)

    def _on_return_inspected(self, sim: Simulation, order: SimOrder, when: datetime) -> None:
        ret = order.returns[-1]
        pending = order.pending_return
        damaged_share = (
            DAMAGED_ON_ARRIVAL_SHARE
            if ret["reason"] == "Damaged on arrival"
            else RETURN_DAMAGED_SHARE
        )
        # Find room for every item first; without room the goods wait at the dock.
        bins: list[int] = []
        for line, quantity in pending:
            bin_id = self._return_bin(sim, order.warehouse_id, line.product_id, quantity, bins)
            if bin_id is None:
                self.waiting_at_dock += 1
                later = next_working_day(when.date() + timedelta(days=1))
                self._plan(
                    at(later, 9.0 + float(self.rng.uniform(0, 7))), "return_inspected", order
                )
                return
            bins.append(bin_id)
        for item, (line, quantity), bin_id in zip(ret["items"], pending, bins, strict=True):
            damaged = bool(self.rng.random() < damaged_share)
            sim.ledger.receive_return(
                line.product_id,
                bin_id,
                quantity,
                when,
                damaged=damaged,
                reason=f"Return {ret['return_number']}: {ret['reason']}",
                return_id=ret["id"],
            )
            item.update(condition="damaged" if damaged else "restock", bin_id=bin_id)
            line.returned += quantity
        ret.update(status="completed", completed_at=when, updated_at=when)
        returned = sum(line.returned for line in order.lines)
        shipped = sum(line.shipped for line in order.lines)
        self.book.transition(
            order,
            "returned",
            when,
            f"Return {ret['return_number']}: {returned} of {shipped} unit(s) returned",
        )
        self.book.close(order)

    def _return_bin(
        self,
        sim: Simulation,
        warehouse_id: int,
        product_id: int,
        quantity: int,
        taken: list[int],
    ) -> int | None:
        """The first returns-zone bin with room (like the application), else a storage
        bin of the product; None when there is no room (bins in `taken` are skipped)."""
        ledger = sim.ledger
        product = ledger.products[product_id]
        candidates = [
            b.id
            for b in self.ctx.bins
            if b.warehouse_id == warehouse_id and b.zone_type == "returns"
        ]
        candidates += ledger.preferences(product, warehouse_id)
        for bin_id in candidates:
            if bin_id not in taken and ledger.room_for(product, bin_id) >= quantity:
                return bin_id
        return None
