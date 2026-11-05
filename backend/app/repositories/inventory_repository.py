"""Database access for inventory rows, movements and stock documents. Never commits."""

from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy import case, select
from sqlalchemy.orm import Session, joinedload

from app.models.inventory import Inventory, ReservationStatus, StockReservation
from app.models.warehouse import Bin, Rack, Shelf, Zone, ZoneType

T = TypeVar("T")


class InventoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, obj: T) -> T:
        self.db.add(obj)
        return obj

    def get_row(self, product_id: int, bin_id: int) -> Inventory | None:
        return self.db.scalar(
            select(Inventory).where(Inventory.product_id == product_id, Inventory.bin_id == bin_id)
        )

    def get_or_create_row(self, product_id: int, bin_id: int) -> Inventory:
        """The stock row of a product in a bin; a new, empty row if there is none yet."""
        row = self.get_row(product_id, bin_id)
        if row is None:
            row = Inventory(
                product_id=product_id,
                bin_id=bin_id,
                quantity_on_hand=0,
                quantity_reserved=0,
                quantity_damaged=0,
            )
            self.db.add(row)
            self.db.flush()  # id needed for movements and audit records
        return row

    def rows_in_bin(self, bin_id: int) -> Sequence[Inventory]:
        """Everything stored in a bin, with products loaded (for capacity checks)."""
        return self.db.scalars(
            select(Inventory)
            .options(joinedload(Inventory.product))
            .where(Inventory.bin_id == bin_id, Inventory.quantity_on_hand > 0)
        ).all()

    def rows_with_available_stock(self, product_id: int) -> Sequence[Inventory]:
        """Rows of a product with available units in active bins, best bins first.

        Order: picking zones before other zones, then racks closest to packing, then
        location code (stable). Used to choose bins automatically when reserving.
        """
        available = (
            Inventory.quantity_on_hand - Inventory.quantity_reserved - Inventory.quantity_damaged
        )
        return self.db.scalars(
            select(Inventory)
            .join(Bin, Inventory.bin_id == Bin.id)
            .join(Shelf, Bin.shelf_id == Shelf.id)
            .join(Rack, Shelf.rack_id == Rack.id)
            .join(Zone, Rack.zone_id == Zone.id)
            .options(joinedload(Inventory.bin))
            .where(Inventory.product_id == product_id, available > 0, Bin.is_active.is_(True))
            .order_by(
                case((Zone.zone_type == ZoneType.PICKING.value, 0), else_=1),
                Rack.distance_to_packing_m,
                Bin.location_code,
            )
        ).all()

    def get_reservation(self, reservation_id: int) -> StockReservation | None:
        return self.db.get(StockReservation, reservation_id)

    def active_reservations_for(
        self, reference_type: str, reference_id: int
    ) -> Sequence[StockReservation]:
        return self.db.scalars(
            select(StockReservation)
            .where(
                StockReservation.reference_type == reference_type,
                StockReservation.reference_id == reference_id,
                StockReservation.status == ReservationStatus.ACTIVE.value,
            )
            .order_by(StockReservation.id)
        ).all()
