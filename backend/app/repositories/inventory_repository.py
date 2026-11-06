"""Database access for inventory rows, movements and stock documents. Never commits."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import Select, case, func, or_, select, true
from sqlalchemy.orm import Session, joinedload

from app.models.catalog import Product
from app.models.inventory import (
    CycleCount,
    Inventory,
    InventoryMovement,
    ReservationStatus,
    StockAdjustment,
    StockReservation,
    StockTransfer,
)
from app.models.warehouse import Bin, Rack, Shelf, Zone, ZoneType

T = TypeVar("T")


def _like(value: str) -> str:
    """Case-insensitive 'contains' pattern with LIKE wildcards escaped."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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

    def rows_with_available_stock(
        self, product_id: int, warehouse_id: int | None = None
    ) -> Sequence[Inventory]:
        """Rows of a product with available units in active bins, best bins first.

        Order: picking zones before other zones, then racks closest to packing, then
        location code (stable). Used to choose bins automatically when reserving.
        With `warehouse_id`, only bins of that warehouse.
        """
        self.db.flush()  # reservations made earlier in this transaction must count
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
            .where(Zone.warehouse_id == warehouse_id if warehouse_id is not None else true())
            .order_by(
                case((Zone.zone_type == ZoneType.PICKING.value, 0), else_=1),
                Rack.distance_to_packing_m,
                Bin.location_code,
            )
        ).all()

    def available_by_warehouse(self, product_ids: Sequence[int]) -> dict[tuple[int, int], int]:
        """{(product_id, warehouse_id): available units in active bins}."""
        self.db.flush()
        available = (
            Inventory.quantity_on_hand - Inventory.quantity_reserved - Inventory.quantity_damaged
        )
        rows = self.db.execute(
            select(Inventory.product_id, Zone.warehouse_id, func.sum(available))
            .join(Bin, Inventory.bin_id == Bin.id)
            .join(Shelf, Bin.shelf_id == Shelf.id)
            .join(Rack, Shelf.rack_id == Rack.id)
            .join(Zone, Rack.zone_id == Zone.id)
            .where(Inventory.product_id.in_(product_ids), Bin.is_active.is_(True))
            .group_by(Inventory.product_id, Zone.warehouse_id)
        ).all()
        return {
            (product_id, warehouse_id): int(total or 0) for product_id, warehouse_id, total in rows
        }

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

    # ------------------------------------------------------------------ searches
    def _page(self, query: Select, order: list[Any], offset: int, limit: int) -> tuple[list, int]:
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        items = list(self.db.scalars(query.order_by(*order).offset(offset).limit(limit)).unique())
        return items, total or 0

    def search_inventory(
        self,
        *,
        offset: int,
        limit: int,
        q: str | None = None,
        product_id: int | None = None,
        bin_id: int | None = None,
        warehouse_id: int | None = None,
        zone_id: int | None = None,
        include_empty: bool = False,
    ) -> tuple[list[Inventory], int]:
        """Stock rows ordered by location code, then SKU."""
        query = (
            select(Inventory)
            .join(Product, Inventory.product_id == Product.id)
            .join(Bin, Inventory.bin_id == Bin.id)
            .join(Shelf, Bin.shelf_id == Shelf.id)
            .join(Rack, Shelf.rack_id == Rack.id)
            .join(Zone, Rack.zone_id == Zone.id)
            .options(joinedload(Inventory.product), joinedload(Inventory.bin))
        )
        if not include_empty:
            query = query.where(Inventory.quantity_on_hand > 0)
        if q:
            pattern = _like(q)
            query = query.where(
                or_(
                    Product.sku.ilike(pattern, escape="\\"),
                    Product.name.ilike(pattern, escape="\\"),
                    Bin.location_code.ilike(pattern, escape="\\"),
                )
            )
        if product_id is not None:
            query = query.where(Inventory.product_id == product_id)
        if bin_id is not None:
            query = query.where(Inventory.bin_id == bin_id)
        if zone_id is not None:
            query = query.where(Zone.id == zone_id)
        if warehouse_id is not None:
            query = query.where(Zone.warehouse_id == warehouse_id)
        return self._page(query, [Bin.location_code, Product.sku], offset, limit)

    def rows_for_product(self, product_id: int) -> Sequence[Inventory]:
        return self.db.scalars(
            select(Inventory)
            .join(Bin, Inventory.bin_id == Bin.id)
            .options(joinedload(Inventory.bin), joinedload(Inventory.product))
            .where(Inventory.product_id == product_id, Inventory.quantity_on_hand > 0)
            .order_by(Bin.location_code)
        ).all()

    def search_movements(
        self,
        *,
        offset: int,
        limit: int,
        product_id: int | None = None,
        bin_id: int | None = None,
        movement_type: str | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[InventoryMovement], int]:
        """Newest first."""
        query = select(InventoryMovement).options(
            joinedload(InventoryMovement.product),
            joinedload(InventoryMovement.bin),
            joinedload(InventoryMovement.created_by),
        )
        filters = {
            InventoryMovement.product_id: product_id,
            InventoryMovement.bin_id: bin_id,
            InventoryMovement.movement_type: movement_type,
            InventoryMovement.reference_type: reference_type,
            InventoryMovement.reference_id: reference_id,
            InventoryMovement.created_by_id: created_by_id,
        }
        for column, value in filters.items():
            if value is not None:
                query = query.where(column == value)
        if since is not None:
            query = query.where(InventoryMovement.created_at >= since)
        if until is not None:
            query = query.where(InventoryMovement.created_at < until)
        order = [InventoryMovement.created_at.desc(), InventoryMovement.id.desc()]
        return self._page(query, order, offset, limit)

    def search_reservations(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        product_id: int | None = None,
        reference_type: str | None = None,
        reference_id: int | None = None,
    ) -> tuple[list[StockReservation], int]:
        query = select(StockReservation).options(
            joinedload(StockReservation.product),
            joinedload(StockReservation.bin),
            joinedload(StockReservation.created_by),
        )
        filters = {
            StockReservation.status: status,
            StockReservation.product_id: product_id,
            StockReservation.reference_type: reference_type,
            StockReservation.reference_id: reference_id,
        }
        for column, value in filters.items():
            if value is not None:
                query = query.where(column == value)
        order = [StockReservation.created_at.desc(), StockReservation.id.desc()]
        return self._page(query, order, offset, limit)

    def search_documents(
        self,
        model: type[StockAdjustment] | type[StockTransfer],
        *,
        offset: int,
        limit: int,
        status: str | None = None,
        product_id: int | None = None,
        requested_by_id: int | None = None,
    ) -> tuple[list, int]:
        """Adjustments or transfers, newest first."""
        query = select(model)
        if status is not None:
            query = query.where(model.status == status)
        if product_id is not None:
            query = query.where(model.product_id == product_id)
        if requested_by_id is not None:
            query = query.where(model.requested_by_id == requested_by_id)
        return self._page(query, [model.created_at.desc(), model.id.desc()], offset, limit)

    def search_cycle_counts(
        self, *, offset: int, limit: int, status: str | None = None, bin_id: int | None = None
    ) -> tuple[list[CycleCount], int]:
        query = select(CycleCount).options(joinedload(CycleCount.bin))
        if status is not None:
            query = query.where(CycleCount.status == status)
        if bin_id is not None:
            query = query.where(CycleCount.bin_id == bin_id)
        return self._page(
            query, [CycleCount.created_at.desc(), CycleCount.id.desc()], offset, limit
        )
