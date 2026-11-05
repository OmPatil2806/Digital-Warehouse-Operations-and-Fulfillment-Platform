"""Inventory operations: every stock change in one place, with the same guarantees.

Each operation runs as ONE database transaction that

1. checks the business rules (product and bin exist, enough stock, bin capacity),
2. changes the `inventory` row of the product in the bin,
3. writes one immutable `inventory_movements` row with the balances after the change,
4. writes an `audit_logs` row ("inventory.receive", "inventory.adjust", ...),

and commits all of it together, or nothing at all.

Quantity model: available = on_hand - reserved - damaged. All changes go through
`_change`, which refuses any result where a number would become negative or reserved +
damaged would exceed on_hand (the database enforces the same rule as a last line of
defence). If another request changed the same row in the meantime, the optimistic lock
(`Inventory.version`) makes the commit fail and the caller gets a 409 "please retry".

This module covers receiving and adjustments (found, lost, damaged, restored, written
off). Reservations, transfers, approvals and cycle counts build on `_change` as well.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.logging import get_logger
from app.exceptions import ConflictError, UnprocessableError
from app.models.catalog import Product
from app.models.inventory import (
    AdjustmentKind,
    DocumentStatus,
    Inventory,
    InventoryMovement,
    MovementType,
    ReferenceType,
    StockAdjustment,
)
from app.models.user import User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import AdjustmentRequest, ReceiveRequest
from app.services.audit_service import AuditService
from app.services.capacity import product_fits_bin

logger = get_logger(__name__)

AUDIT_ENTITY = "inventory"


# ------------------------------------------------------------------------- errors
class InsufficientStockError(ConflictError):
    """Not enough units for the operation (e.g. removing more than is available)."""


class CapacityExceededError(ConflictError):
    """The units would not fit into the bin (weight or volume)."""


class StockChangedError(ConflictError):
    message = "The stock was changed by someone else at the same time. Please try again."


# ------------------------------------------------------------------------- result
@dataclass
class StockOperationResult:
    """What an operation changed: the inventory row(s) and the movements written."""

    inventory: Inventory
    movements: list[InventoryMovement] = field(default_factory=list)
    adjustment: StockAdjustment | None = None


# How each adjustment kind changes (on_hand, damaged), per unit, and its movement type.
ADJUSTMENT_EFFECTS: dict[AdjustmentKind, tuple[int, int, MovementType]] = {
    AdjustmentKind.INCREASE: (+1, 0, MovementType.ADJUSTMENT),
    AdjustmentKind.DECREASE: (-1, 0, MovementType.ADJUSTMENT),
    AdjustmentKind.DAMAGE: (0, +1, MovementType.DAMAGE),
    AdjustmentKind.RESTORE: (0, -1, MovementType.RESTORE),
    AdjustmentKind.WRITE_OFF: (-1, -1, MovementType.WRITE_OFF),
}


class InventoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = InventoryRepository(db)
        self.audit = AuditService(db)

    # ---------------------------------------------------------------- receive
    def receive(self, data: ReceiveRequest, *, user: User | None) -> StockOperationResult:
        """Put received goods into a bin (on_hand +). Checks the bin's capacity."""
        product = self._product(data.product_id)
        bin_ = self._bin(data.bin_id)
        self._check_fits(product, bin_, data.quantity)

        row = self.repo.get_or_create_row(product.id, bin_.id)
        before = _quantities(row)
        movement = self._change(
            row,
            MovementType.RECEIPT,
            data.quantity,
            on_hand=data.quantity,
            reason=data.reason,
            user=user,
        )
        self.audit.record(
            "inventory.receive",
            AUDIT_ENTITY,
            row.id,
            summary=f"Received {data.quantity} x {product.sku} into {bin_.location_code}",
            changes=_diff(before, row),
            actor=user,
        )
        self._commit()
        logger.info("Received %s x %s into %s", data.quantity, product.sku, bin_.location_code)
        return StockOperationResult(inventory=row, movements=[movement])

    # ------------------------------------------------------------- adjustments
    def adjust(self, data: AdjustmentRequest, *, user: User | None) -> StockOperationResult:
        """Apply a correction immediately (the adjustment document is stored as completed).

        Who may adjust without approval is decided by the API (manager approval comes in
        a later step); the service only guarantees the stock rules.
        """
        product = self._product(data.product_id, allow_archived=True)
        bin_ = self._bin(data.bin_id, allow_archived=True)
        now = datetime.now(UTC)
        adjustment = self.repo.add(
            StockAdjustment(
                product_id=product.id,
                bin_id=bin_.id,
                kind=data.kind,
                quantity=data.quantity,
                reason=data.reason,
                status=DocumentStatus.COMPLETED,
                requested_by_id=user.id if user else None,
                decided_by_id=user.id if user else None,
                decided_at=now,
            )
        )
        try:
            self.db.flush()  # the adjustment id is the movement's reference
            result = self.apply_adjustment(adjustment, product=product, bin_=bin_, user=user)
        except Exception:
            self.db.rollback()  # nothing of a refused adjustment is kept
            raise
        self._commit()
        return result

    def apply_adjustment(
        self,
        adjustment: StockAdjustment,
        *,
        product: Product,
        bin_: Bin,
        user: User | None,
    ) -> StockOperationResult:
        """Change the stock as `adjustment` says (no commit; also used for approvals)."""
        kind = AdjustmentKind(adjustment.kind)
        quantity = adjustment.quantity
        on_hand_sign, damaged_sign, movement_type = ADJUSTMENT_EFFECTS[kind]

        if kind is AdjustmentKind.INCREASE:
            self._require_active(product, bin_)
            self._check_fits(product, bin_, quantity)
            row = self.repo.get_or_create_row(product.id, bin_.id)
        else:
            row = self.repo.get_row(product.id, bin_.id)
            if row is None:
                raise InsufficientStockError(f"There is no {product.sku} in {bin_.location_code}")

        before = _quantities(row)
        movement = self._change(
            row,
            movement_type,
            quantity,
            on_hand=on_hand_sign * quantity,
            damaged=damaged_sign * quantity,
            reference=(ReferenceType.ADJUSTMENT, adjustment.id),
            reason=adjustment.reason,
            user=user,
        )
        self.audit.record(
            "inventory.adjust",
            AUDIT_ENTITY,
            row.id,
            summary=(
                f"{kind.value.replace('_', ' ').capitalize()}: {quantity} x {product.sku} "
                f"in {bin_.location_code} ({adjustment.reason})"
            ),
            changes=_diff(before, row),
            actor=user,
        )
        logger.info("Adjustment %s applied: %s", adjustment.id, movement)
        return StockOperationResult(inventory=row, movements=[movement], adjustment=adjustment)

    # ------------------------------------------------------- the one way to change
    def _change(
        self,
        row: Inventory,
        movement_type: MovementType,
        quantity: int,
        *,
        on_hand: int = 0,
        reserved: int = 0,
        damaged: int = 0,
        reference: tuple[ReferenceType, int] | None = None,
        reason: str | None = None,
        user: User | None,
    ) -> InventoryMovement:
        """Apply signed deltas to `row` and write the matching movement (no commit)."""
        new_on_hand = row.quantity_on_hand + on_hand
        new_reserved = row.quantity_reserved + reserved
        new_damaged = row.quantity_damaged + damaged
        _check_quantities(row, new_on_hand, new_reserved, new_damaged)

        row.quantity_on_hand = new_on_hand
        row.quantity_reserved = new_reserved
        row.quantity_damaged = new_damaged
        reference_type, reference_id = reference or (None, None)
        return self.repo.add(
            InventoryMovement(
                movement_type=movement_type,
                product_id=row.product_id,
                bin_id=row.bin_id,
                quantity=quantity,
                on_hand_delta=on_hand,
                reserved_delta=reserved,
                damaged_delta=damaged,
                on_hand_after=new_on_hand,
                reserved_after=new_reserved,
                damaged_after=new_damaged,
                reference_type=reference_type,
                reference_id=reference_id,
                reason=reason,
                created_by_id=user.id if user else None,
            )
        )

    # ------------------------------------------------------------------ checks
    def _product(self, product_id: int, *, allow_archived: bool = False) -> Product:
        product = self.db.get(Product, product_id)
        if product is None:
            raise UnprocessableError("Product not found")
        if not allow_archived and not product.is_active:
            raise UnprocessableError(f"Product {product.sku} is archived")
        return product

    def _bin(self, bin_id: int, *, allow_archived: bool = False) -> Bin:
        bin_ = self.db.get(Bin, bin_id)
        if bin_ is None:
            raise UnprocessableError("Bin not found")
        if not allow_archived and not bin_.is_active:
            raise UnprocessableError(f"Bin {bin_.location_code} is archived")
        return bin_

    @staticmethod
    def _require_active(product: Product, bin_: Bin) -> None:
        """Stock can only be added for active products into active bins."""
        if not product.is_active:
            raise UnprocessableError(f"Product {product.sku} is archived")
        if not bin_.is_active:
            raise UnprocessableError(f"Bin {bin_.location_code} is archived")

    def _check_fits(self, product: Product, bin_: Bin, quantity: int) -> None:
        weight, volume = self.bin_load(bin_.id)
        check = product_fits_bin(
            product, bin_, quantity, current_weight_kg=weight, current_volume_cm3=volume
        )
        if not check.fits:
            raise CapacityExceededError(
                f"{quantity} x {product.sku} do not fit into {bin_.location_code}: "
                + "; ".join(check.reasons)
            )

    def bin_load(self, bin_id: int) -> tuple[Decimal, Decimal]:
        """Total weight (kg) and volume (cm³) of everything in a bin, damaged units too."""
        rows: Sequence[Inventory] = self.repo.rows_in_bin(bin_id)
        weight = sum((r.product.weight_kg * r.quantity_on_hand for r in rows), Decimal("0"))
        volume = sum((r.product.volume_cm3 * r.quantity_on_hand for r in rows), Decimal("0"))
        return weight, volume

    def _commit(self) -> None:
        try:
            self.db.commit()
        except StaleDataError as exc:  # another request updated the same row first
            self.db.rollback()
            raise StockChangedError() from exc
        except IntegrityError as exc:  # e.g. two requests created the same row at once
            self.db.rollback()
            raise StockChangedError() from exc


# ---------------------------------------------------------------------- helpers
def _quantities(row: Inventory) -> dict[str, int]:
    return {
        "quantity_on_hand": row.quantity_on_hand,
        "quantity_reserved": row.quantity_reserved,
        "quantity_damaged": row.quantity_damaged,
    }


def _diff(before: dict[str, int], row: Inventory) -> dict[str, dict[str, int]]:
    after = _quantities(row)
    return {
        key: {"old": before[key], "new": after[key]} for key in after if before[key] != after[key]
    }


def _check_quantities(row: Inventory, on_hand: int, reserved: int, damaged: int) -> None:
    """Refuse results that break the quantity model, with a message a person understands."""
    available = row.quantity_available
    if on_hand < 0:
        raise InsufficientStockError(f"Only {row.quantity_on_hand} units on hand")
    if damaged < 0:
        raise InsufficientStockError(f"Only {row.quantity_damaged} damaged units")
    if reserved < 0:
        raise InsufficientStockError(f"Only {row.quantity_reserved} units reserved")
    if reserved + damaged > on_hand:
        raise InsufficientStockError(
            f"Only {available} units available "
            f"({row.quantity_reserved} reserved, {row.quantity_damaged} damaged)"
        )
