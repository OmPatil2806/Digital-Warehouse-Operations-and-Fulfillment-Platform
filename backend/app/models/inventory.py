"""Inventory at bin level and its full, traceable history.

Quantity model (one `inventory` row per product and bin):

    available = on_hand - reserved - damaged

    on_hand   units physically in the bin (good and damaged)
    reserved  good units promised to an order or a manual reservation
    damaged   units in the bin that cannot be sold

Every change to these numbers writes exactly one row to `inventory_movements` (a transfer
writes two: out of one bin, into another). Movements are immutable: the database refuses
UPDATE and DELETE on that table (triggers created by the migration), so the history can be
trusted for audits and for the ML features of Phase 7/8.

Transfers, adjustments and cycle counts are *documents* with a status. Staff can create
them as requests (`pending`) that a manager approves; the stock only changes, and the
movements are only written, when a document is completed.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Product
from app.models.mixins import IdMixin, TimestampMixin
from app.models.user import User
from app.models.warehouse import Bin


def _one_of(column: str, values: type[StrEnum]) -> str:
    """SQL for `column IN ('a', 'b', ...)` built from an enum, so both stay in sync."""
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


# --------------------------------------------------------------------------- enums
class MovementType(StrEnum):
    """Why a quantity changed."""

    RECEIPT = "receipt"  # goods received into a bin (on_hand +)
    ADJUSTMENT = "adjustment"  # correction found or lost (on_hand +/-)
    DAMAGE = "damage"  # good units marked as damaged (damaged +)
    RESTORE = "restore"  # damaged units found to be sellable after all (damaged -)
    WRITE_OFF = "write_off"  # damaged units removed from stock (on_hand -, damaged -)
    TRANSFER_OUT = "transfer_out"  # moved out of this bin (on_hand -)
    TRANSFER_IN = "transfer_in"  # moved into this bin (on_hand +)
    RESERVATION = "reservation"  # promised to an order (reserved +)
    RELEASE = "release"  # reservation cancelled (reserved -)
    CYCLE_COUNT = "cycle_count"  # correction after a physical count (on_hand +/-)
    PICK = "pick"  # picked for an order, Phase 5 (on_hand -, reserved -)
    RETURN = "return"  # customer return put back into stock, Phase 5 (on_hand +)


class ReferenceType(StrEnum):
    """The document a movement belongs to (`reference_id` is that document's id)."""

    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    RESERVATION = "reservation"
    CYCLE_COUNT = "cycle_count"
    ORDER = "order"  # Phase 5
    RETURN = "return"  # Phase 5


class DocumentStatus(StrEnum):
    """Life cycle of transfers and adjustments."""

    PENDING = "pending"  # requested, waiting for a manager
    COMPLETED = "completed"  # applied to the stock (movements written)
    REJECTED = "rejected"  # refused by a manager
    CANCELLED = "cancelled"  # withdrawn by the requester


class AdjustmentKind(StrEnum):
    INCREASE = "increase"  # on_hand +  (units found)
    DECREASE = "decrease"  # on_hand -  (units lost / missing)
    DAMAGE = "damage"  # damaged +
    RESTORE = "restore"  # damaged -
    WRITE_OFF = "write_off"  # on_hand -, damaged -


class ReservationStatus(StrEnum):
    ACTIVE = "active"  # units are held
    RELEASED = "released"  # cancelled, units available again
    FULFILLED = "fulfilled"  # picked for the order (Phase 5)


class CycleCountStatus(StrEnum):
    OPEN = "open"  # counting in progress
    SUBMITTED = "submitted"  # counted, waiting for a manager to approve the differences
    COMPLETED = "completed"  # differences applied as cycle_count movements
    CANCELLED = "cancelled"


# -------------------------------------------------------------------------- tables
class Inventory(IdMixin, TimestampMixin, Base):
    """Current stock of one product in one bin."""

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "bin_id", name="uq_inventory_product_id_bin_id"),
        CheckConstraint("quantity_on_hand >= 0", name="on_hand_not_negative"),
        CheckConstraint("quantity_reserved >= 0", name="reserved_not_negative"),
        CheckConstraint("quantity_damaged >= 0", name="damaged_not_negative"),
        # Reserved units must be good units: available can never be negative.
        CheckConstraint(
            "quantity_reserved + quantity_damaged <= quantity_on_hand",
            name="available_not_negative",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    quantity_damaged: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    # Optimistic locking: an UPDATE based on stale numbers fails instead of silently
    # overwriting a change made by another request in the meantime.
    version: Mapped[int] = mapped_column(server_default="1", nullable=False)

    product: Mapped[Product] = relationship()
    bin: Mapped[Bin] = relationship()

    __mapper_args__ = {"version_id_col": version}

    @property
    def quantity_available(self) -> int:
        return self.quantity_on_hand - self.quantity_reserved - self.quantity_damaged

    def __repr__(self) -> str:
        return (
            f"<Inventory product={self.product_id} bin={self.bin_id} "
            f"on_hand={self.quantity_on_hand} reserved={self.quantity_reserved} "
            f"damaged={self.quantity_damaged}>"
        )


class InventoryMovement(IdMixin, Base):
    """One immutable change of stock in one bin (the audit trail of every unit).

    The deltas say which numbers changed; the `*_after` columns are the balances of the
    inventory row right after the change, so any point in history can be read directly.
    """

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(_one_of("movement_type", MovementType), name="valid_movement_type"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "on_hand_delta != 0 OR reserved_delta != 0 OR damaged_delta != 0",
            name="changes_something",
        ),
        CheckConstraint(
            "on_hand_after >= 0 AND reserved_after >= 0 AND damaged_after >= 0 "
            "AND reserved_after + damaged_after <= on_hand_after",
            name="balances_valid",
        ),
        CheckConstraint(
            f"reference_type IS NULL OR {_one_of('reference_type', ReferenceType)}",
            name="valid_reference_type",
        ),
        CheckConstraint(
            "(reference_type IS NULL) = (reference_id IS NULL)", name="reference_complete"
        ),
        Index("ix_inventory_movements_product_id_created_at", "product_id", "created_at"),
        Index("ix_inventory_movements_bin_id_created_at", "bin_id", "created_at"),
        Index("ix_inventory_movements_reference", "reference_type", "reference_id"),
    )

    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    bin_id: Mapped[int] = mapped_column(ForeignKey("bins.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)  # size of the operation, always > 0
    on_hand_delta: Mapped[int] = mapped_column(nullable=False)
    reserved_delta: Mapped[int] = mapped_column(nullable=False)
    damaged_delta: Mapped[int] = mapped_column(nullable=False)
    on_hand_after: Mapped[int] = mapped_column(nullable=False)
    reserved_after: Mapped[int] = mapped_column(nullable=False)
    damaged_after: Mapped[int] = mapped_column(nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(20))
    reference_id: Mapped[int | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(255))
    # NULL = done by the system (seed data, background jobs). Users are never deleted.
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    product: Mapped[Product] = relationship()
    bin: Mapped[Bin] = relationship()
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<InventoryMovement {self.movement_type} x{self.quantity} bin={self.bin_id}>"


class _DecisionMixin:
    """Who requested a document and who approved or rejected it."""

    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str | None] = mapped_column(String(255))


class StockTransfer(IdMixin, TimestampMixin, _DecisionMixin, Base):
    """Moving units of one product from one bin to another."""

    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint(_one_of("status", DocumentStatus), name="valid_status"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("from_bin_id != to_bin_id", name="different_bins"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    from_bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    to_bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.PENDING, server_default="pending", index=True
    )
    reason: Mapped[str | None] = mapped_column(String(255))

    product: Mapped[Product] = relationship()
    from_bin: Mapped[Bin] = relationship(foreign_keys=[from_bin_id])
    to_bin: Mapped[Bin] = relationship(foreign_keys=[to_bin_id])
    requested_by: Mapped[User | None] = relationship(foreign_keys="StockTransfer.requested_by_id")
    decided_by: Mapped[User | None] = relationship(foreign_keys="StockTransfer.decided_by_id")

    def __repr__(self) -> str:
        return f"<StockTransfer {self.id} x{self.quantity} {self.status}>"


class StockAdjustment(IdMixin, TimestampMixin, _DecisionMixin, Base):
    """A correction of stock in one bin (found, lost, damaged, restored, written off)."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        CheckConstraint(_one_of("status", DocumentStatus), name="valid_status"),
        CheckConstraint(_one_of("kind", AdjustmentKind), name="valid_kind"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.PENDING, server_default="pending", index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)  # always required

    product: Mapped[Product] = relationship()
    bin: Mapped[Bin] = relationship()
    requested_by: Mapped[User | None] = relationship(foreign_keys="StockAdjustment.requested_by_id")
    decided_by: Mapped[User | None] = relationship(foreign_keys="StockAdjustment.decided_by_id")

    def __repr__(self) -> str:
        return f"<StockAdjustment {self.id} {self.kind} x{self.quantity} {self.status}>"


class StockReservation(IdMixin, TimestampMixin, Base):
    """Units of a product in a bin held for an order (Phase 5) or by a manager."""

    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint(_one_of("status", ReservationStatus), name="valid_status"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            f"reference_type IS NULL OR {_one_of('reference_type', ReferenceType)}",
            name="valid_reference_type",
        ),
        CheckConstraint(
            "(reference_type IS NULL) = (reference_id IS NULL)", name="reference_complete"
        ),
        Index("ix_stock_reservations_reference", "reference_type", "reference_id"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ReservationStatus.ACTIVE, server_default="active", index=True
    )
    # What the units are held for, e.g. ("order", 42). NULL = manual reservation.
    reference_type: Mapped[str | None] = mapped_column(String(20))
    reference_id: Mapped[int | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # released / fulfilled

    product: Mapped[Product] = relationship()
    bin: Mapped[Bin] = relationship()
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<StockReservation {self.id} x{self.quantity} {self.status}>"


class CycleCount(IdMixin, TimestampMixin, _DecisionMixin, Base):
    """A physical count of one bin, compared with what the system expects."""

    __tablename__ = "cycle_counts"
    __table_args__ = (CheckConstraint(_one_of("status", CycleCountStatus), name="valid_status"),)

    bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=CycleCountStatus.OPEN, server_default="open", index=True
    )
    note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    bin: Mapped[Bin] = relationship()
    requested_by: Mapped[User | None] = relationship(foreign_keys="CycleCount.requested_by_id")
    decided_by: Mapped[User | None] = relationship(foreign_keys="CycleCount.decided_by_id")
    lines: Mapped[list["CycleCountLine"]] = relationship(
        back_populates="cycle_count",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CycleCountLine.id",
    )

    def __repr__(self) -> str:
        return f"<CycleCount {self.id} bin={self.bin_id} {self.status}>"


class CycleCountLine(IdMixin, Base):
    """Expected vs counted quantity of one product in the counted bin."""

    __tablename__ = "cycle_count_lines"
    __table_args__ = (
        UniqueConstraint(
            "cycle_count_id", "product_id", name="uq_cycle_count_lines_cycle_count_id_product_id"
        ),
        CheckConstraint("expected_quantity >= 0", name="expected_not_negative"),
        CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0", name="counted_not_negative"
        ),
    )

    cycle_count_id: Mapped[int] = mapped_column(
        ForeignKey("cycle_counts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    expected_quantity: Mapped[int] = mapped_column(nullable=False)  # on_hand when counting began
    counted_quantity: Mapped[int | None] = mapped_column()  # NULL = not counted yet

    cycle_count: Mapped[CycleCount] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()

    @property
    def variance(self) -> int | None:
        """Counted minus expected (negative = units missing)."""
        if self.counted_quantity is None:
            return None
        return self.counted_quantity - self.expected_quantity

    def __repr__(self) -> str:
        return f"<CycleCountLine product={self.product_id} variance={self.variance}>"
