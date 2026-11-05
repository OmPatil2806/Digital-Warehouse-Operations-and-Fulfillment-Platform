"""Database access for inventory rows, movements and stock documents. Never commits."""

from collections.abc import Sequence
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.inventory import Inventory

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
