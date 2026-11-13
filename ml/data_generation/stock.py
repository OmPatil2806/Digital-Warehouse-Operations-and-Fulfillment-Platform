"""In-memory stock of the simulation, written to the database as movements.

The ledger follows the application's rules (backend inventory_service.py):

- every change is one ``inventory_movements`` row with the balances after it,
- on hand, reserved and damaged never go negative; reserved + damaged <= on hand,
- a bin never holds more weight or volume than its limits (all units count).

Weights and volumes are kept as integers (grams, cm³ x 1000) so capacity checks are
exact, like the Decimal checks of the application.

Put-away (slotting) rules, which the slotting use case of Phase 8 can learn from:

1. a product goes to a zone of its storage type (cold, hazardous, bulk, picking),
   falling back to picking and then bulk when there is none or no room;
2. bins already holding the product are filled first, then empty bins;
3. heavy products (>= 8 kg) prefer low shelves; fast movers prefer bins close to
   packing; slow movers are kept to the back, leaving the front free.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.models import Inventory, InventoryMovement, StockReservation
from data_generation.context import BinInfo, GenerationContext, ProductInfo

HEAVY_KG = Decimal(8)
FAST_MOVER_SHARE = 0.2  # the fastest-selling fifth of the catalog
FALLBACK_ZONES = ("picking", "bulk")


@dataclass(slots=True)
class Reservation:
    """Units of a product in one bin held for an order (backend: stock_reservations)."""

    id: int
    product_id: int
    bin_id: int
    quantity: int
    order_id: int
    reason: str
    created: datetime
    status: str = "active"  # active -> released | fulfilled
    closed: datetime | None = None


@dataclass
class StockRow:
    on_hand: int = 0
    reserved: int = 0
    damaged: int = 0
    first_movement: datetime | None = None
    last_movement: datetime | None = None

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved - self.damaged


def _grams(kg: Decimal) -> int:
    return int(kg * 1000)


def _milli_cm3(cm3: Decimal | int) -> int:
    return int(Decimal(cm3) * 1000)


class StockLedger:
    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.rows: dict[tuple[int, int], StockRow] = {}
        self.product_bins: dict[tuple[int, int], list[int]] = {}  # (product, warehouse)
        self.bins = {b.id: b for b in ctx.bins}
        self.products = {p.id: p for p in ctx.products}
        self.load = {b.id: [0, 0] for b in ctx.bins}  # bin -> [grams, cm³ x 1000]
        self.limit = {
            b.id: (_grams(b.max_weight_kg), _milli_cm3(b.max_volume_cm3)) for b in ctx.bins
        }
        rates = sorted((p.profile.base_rate for p in ctx.products), reverse=True)
        self.fast_threshold = rates[max(0, int(len(rates) * FAST_MOVER_SHARE) - 1)]
        self._preferences: dict[tuple[int, int], list[int]] = {}
        self._movements: list[dict] = []
        self.movement_count = 0
        self.reservations: dict[int, Reservation] = {}  # active ones
        self._closed_reservations: list[Reservation] = []
        self._reservation_ids = 0

    # --------------------------------------------------------------------- queries
    def row(self, product_id: int, bin_id: int) -> StockRow:
        key = (product_id, bin_id)
        if key not in self.rows:
            self.rows[key] = StockRow()
        return self.rows[key]

    def bins_of(self, product_id: int, warehouse_id: int) -> list[int]:
        return self.product_bins.get((product_id, warehouse_id), [])

    def available(self, product_id: int, warehouse_id: int) -> int:
        return sum(
            self.rows[(product_id, b)].available for b in self.bins_of(product_id, warehouse_id)
        )

    def on_hand(self, product_id: int, warehouse_id: int) -> int:
        return sum(
            self.rows[(product_id, b)].on_hand for b in self.bins_of(product_id, warehouse_id)
        )

    def room_for(self, product: ProductInfo, bin_id: int) -> int:
        """How many more units of the product fit into the bin."""
        grams, volume = self.load[bin_id]
        max_grams, max_volume = self.limit[bin_id]
        unit_grams, unit_volume = _grams(product.weight_kg), _milli_cm3(product.volume_cm3)
        return max(0, min((max_grams - grams) // unit_grams, (max_volume - volume) // unit_volume))

    # ------------------------------------------------------------------ put-away
    def preferences(self, product: ProductInfo, warehouse_id: int) -> list[int]:
        """Candidate bins of the warehouse for the product, best first (cached)."""
        key = (product.id, warehouse_id)
        if key not in self._preferences:
            in_warehouse = [b for b in self.ctx.bins if b.warehouse_id == warehouse_id]
            types = (product.storage, *FALLBACK_ZONES)
            heavy = product.weight_kg >= HEAVY_KG
            fast = product.profile.base_rate >= self.fast_threshold

            def order(b: BinInfo) -> tuple:
                zone_rank = types.index(b.zone_type)
                if heavy:
                    return (zone_rank, b.level, b.distance_m, b.id)
                if fast:
                    return (zone_rank, b.distance_m, b.level, b.id)
                return (zone_rank, -b.distance_m, b.level, b.id)

            candidates = [b for b in in_warehouse if b.zone_type in types]
            self._preferences[key] = [b.id for b in sorted(candidates, key=order)]
        return self._preferences[key]

    def receive(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: int,
        when: datetime,
        *,
        reason: str,
    ) -> int:
        """Put received units away; returns how many fitted (the rest has no room)."""
        product = self.products[product_id]
        received = 0
        for bin_id in self._put_away_order(product, warehouse_id):
            units = min(quantity - received, self.room_for(product, bin_id))
            if units > 0:
                self._change(
                    product, bin_id, warehouse_id, "receipt", units, units, 0, 0, when, reason
                )
                received += units
                if received == quantity:
                    break
        return received

    def _put_away_order(self, product: ProductInfo, warehouse_id: int) -> Iterator[int]:
        """Bins holding the product, then empty bins, then shared bins (lazily)."""
        seen: set[int] = set()
        for bin_id in list(self.bins_of(product.id, warehouse_id)):
            seen.add(bin_id)
            yield bin_id
        preferences = self.preferences(product, warehouse_id)
        for bin_id in preferences:
            if bin_id not in seen and self.load[bin_id][0] == 0:
                seen.add(bin_id)
                yield bin_id
        for bin_id in preferences:
            if bin_id not in seen:
                yield bin_id

    # ---------------------------------------------------------------- reservations
    def reservation_order(self, product_id: int, warehouse_id: int) -> list[int]:
        """Bins to reserve from, like the application: picking zones first, then racks
        closest to packing, then location (bin ids follow location codes)."""
        bins = self.bins_of(product_id, warehouse_id)
        return sorted(
            bins,
            key=lambda b: (self.bins[b].zone_type != "picking", self.bins[b].distance_m, b),
        )

    def reserve(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: int,
        when: datetime,
        *,
        order_id: int,
        reason: str,
    ) -> list[Reservation]:
        """Hold up to `quantity` available units for an order (one reservation per bin)."""
        product = self.products[product_id]
        made: list[Reservation] = []
        remaining = quantity
        for bin_id in self.reservation_order(product_id, warehouse_id):
            units = min(remaining, self.rows[(product_id, bin_id)].available)
            if units <= 0:
                continue
            self._reservation_ids += 1
            reservation = Reservation(
                self._reservation_ids, product_id, bin_id, units, order_id, reason, when
            )
            self.reservations[reservation.id] = reservation
            self._change(
                product,
                bin_id,
                warehouse_id,
                "reservation",
                units,
                0,
                units,
                0,
                when,
                reason,
                reference=("reservation", reservation.id),
            )
            made.append(reservation)
            remaining -= units
            if remaining == 0:
                break
        return made

    def release(self, reservation_id: int, when: datetime, *, reason: str) -> None:
        """Give the held units back (order cancelled)."""
        reservation = self.reservations.pop(reservation_id)
        product = self.products[reservation.product_id]
        self._change(
            product,
            reservation.bin_id,
            self.bins[reservation.bin_id].warehouse_id,
            "release",
            reservation.quantity,
            0,
            -reservation.quantity,
            0,
            when,
            reason,
            reference=("reservation", reservation.id),
        )
        self._close(reservation, "released", when)

    def pick(
        self,
        reservation_id: int,
        picked: int,
        when: datetime,
        *,
        reason: str,
        reference: tuple[str, int],
    ) -> None:
        """Take reserved units out for shipping; units not picked are released."""
        reservation = self.reservations.pop(reservation_id)
        product = self.products[reservation.product_id]
        warehouse_id = self.bins[reservation.bin_id].warehouse_id
        if not 0 <= picked <= reservation.quantity:
            raise AssertionError("cannot pick more than was reserved")
        if picked:
            self._change(
                product,
                reservation.bin_id,
                warehouse_id,
                "pick",
                picked,
                -picked,
                -picked,
                0,
                when,
                reason,
                reference=reference,
            )
        not_picked = reservation.quantity - picked
        if not_picked:
            self._change(
                product,
                reservation.bin_id,
                warehouse_id,
                "release",
                not_picked,
                0,
                -not_picked,
                0,
                when,
                f"{reason}: {not_picked} not picked",
                reference=("reservation", reservation.id),
            )
        self._close(reservation, "fulfilled" if picked else "released", when)

    def _close(self, reservation: Reservation, status: str, when: datetime) -> None:
        reservation.status = status
        reservation.closed = when
        self._closed_reservations.append(reservation)
        if len(self._closed_reservations) >= self.ctx.config.batch_size:
            self._write_reservations(self._closed_reservations)
            self._closed_reservations = []

    def _write_reservations(self, reservations: list[Reservation]) -> None:
        self.ctx.writer.insert(
            StockReservation.__table__,
            (
                {
                    "id": r.id,
                    "product_id": r.product_id,
                    "bin_id": r.bin_id,
                    "quantity": r.quantity,
                    "status": r.status,
                    "reference_type": "order",
                    "reference_id": r.order_id,
                    "reason": r.reason,
                    "created_by_id": None,
                    "closed_at": r.closed,
                    "created_at": r.created,
                    "updated_at": r.closed or r.created,
                }
                for r in reservations
            ),
        )

    def remove(
        self,
        product_id: int,
        warehouse_id: int,
        quantity: int,
        when: datetime,
        *,
        movement_type: str,
        reason: str,
    ) -> int:
        """Take available units out (from the fullest bin first); returns units taken."""
        product = self.products[product_id]
        taken = 0
        bins = sorted(
            self.bins_of(product_id, warehouse_id),
            key=lambda b: -self.rows[(product_id, b)].available,
        )
        for bin_id in bins:
            if taken == quantity:
                break
            units = min(quantity - taken, self.rows[(product_id, bin_id)].available)
            if units > 0:
                self._change(
                    product, bin_id, warehouse_id, movement_type, units, -units, 0, 0, when, reason
                )
                taken += units
        return taken

    # ------------------------------------------------------------------ recording
    def _change(
        self,
        product: ProductInfo,
        bin_id: int,
        warehouse_id: int,
        movement_type: str,
        quantity: int,
        on_hand: int,
        reserved: int,
        damaged: int,
        when: datetime,
        reason: str | None,
        reference: tuple[str, int] | None = None,
    ) -> None:
        row = self.row(product.id, bin_id)
        row.on_hand += on_hand
        row.reserved += reserved
        row.damaged += damaged
        if row.on_hand < 0 or row.reserved < 0 or row.damaged < 0 or row.available < 0:
            raise AssertionError(f"stock rule broken for {product.sku} in bin {bin_id}")
        if on_hand:
            self.load[bin_id][0] += on_hand * _grams(product.weight_kg)
            self.load[bin_id][1] += on_hand * _milli_cm3(product.volume_cm3)
            grams, volume = self.load[bin_id]
            if grams > self.limit[bin_id][0] or volume > self.limit[bin_id][1]:
                raise AssertionError(f"bin {bin_id} over capacity")
        bins = self.product_bins.setdefault((product.id, warehouse_id), [])
        if bin_id not in bins:
            bins.append(bin_id)
        row.first_movement = row.first_movement or when
        row.last_movement = when
        self._movements.append(
            {
                "movement_type": movement_type,
                "product_id": product.id,
                "bin_id": bin_id,
                "quantity": quantity,
                "on_hand_delta": on_hand,
                "reserved_delta": reserved,
                "damaged_delta": damaged,
                "on_hand_after": row.on_hand,
                "reserved_after": row.reserved,
                "damaged_after": row.damaged,
                "reference_type": reference[0] if reference else None,
                "reference_id": reference[1] if reference else None,
                "reason": reason,
                "created_by_id": None,
                "created_at": when,
            }
        )
        self.movement_count += 1
        if len(self._movements) >= self.ctx.config.batch_size:
            self.flush()

    def flush(self) -> None:
        if self._movements:
            self.ctx.writer.insert(InventoryMovement.__table__, self._movements)
            self._movements = []

    def finish(self) -> None:
        """Write the remaining movements, reservations and the final stock rows."""
        self.flush()
        self._write_reservations(self._closed_reservations + list(self.reservations.values()))
        self.ctx.writer.insert(Inventory.__table__, self._inventory_rows())

    def _inventory_rows(self) -> Iterator[dict]:
        for (product_id, bin_id), row in sorted(self.rows.items()):
            if row.first_movement is None:
                continue
            yield {
                "product_id": product_id,
                "bin_id": bin_id,
                "quantity_on_hand": row.on_hand,
                "quantity_reserved": row.reserved,
                "quantity_damaged": row.damaged,
                "version": 1,
                "created_at": row.first_movement,
                "updated_at": row.last_movement,
            }
