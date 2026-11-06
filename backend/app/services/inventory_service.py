"""Inventory operations: every stock change in one place, with the same guarantees.

Each operation runs as ONE database transaction that

1. checks the business rules (product and bin exist, enough stock, bin capacity),
2. changes the `inventory` row of the product in the bin,
3. writes one immutable `inventory_movements` row with the balances after the change,
4. writes an `audit_logs` row ("inventory.receive", "inventory.adjust", ...),

and commits all of it together, or nothing at all.

Quantity model: available = on_hand - reserved - damaged. All changes go through
`change`, which refuses any result where a number would become negative or reserved +
damaged would exceed on_hand (the database enforces the same rule as a last line of
defence). If another request changed the same row in the meantime, the optimistic lock
(`Inventory.version`) makes the commit fail and the caller gets a 409 "please retry".

Operations: receiving, adjustments (found, lost, damaged, restored, written off),
reservations (reserve / release) and transfers between bins. Approvals and cycle counts
build on the same primitives.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Product
from app.models.inventory import (
    AdjustmentKind,
    DocumentStatus,
    Inventory,
    InventoryMovement,
    MovementType,
    ReferenceType,
    ReservationStatus,
    StockAdjustment,
    StockReservation,
    StockTransfer,
)
from app.models.user import User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    AdjustmentRequest,
    ReceiveRequest,
    ReleaseRequest,
    ReserveRequest,
    TransferRequest,
)
from app.services.alert_service import AlertService
from app.services.audit_service import AuditService
from app.services.capacity import product_fits_bin

logger = get_logger(__name__)

AUDIT_ENTITY = "inventory"
TOUCHED_KEY = "_stock_touched"  # session.info: (product_id, bin_id) pairs changed


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


@dataclass
class ReservationResult:
    """One reservation per bin the units were taken from."""

    reservations: list[StockReservation]
    movements: list[InventoryMovement]

    @property
    def quantity(self) -> int:
        return sum(r.quantity for r in self.reservations)


@dataclass
class TransferResult:
    transfer: StockTransfer
    source: Inventory
    target: Inventory
    movements: list[InventoryMovement]


class ReservationNotFoundError(NotFoundError):
    message = "Reservation not found"


# How each adjustment kind changes (on_hand, damaged), per unit, and its movement type.
ADJUSTMENT_EFFECTS: dict[AdjustmentKind, tuple[int, int, MovementType]] = {
    AdjustmentKind.INCREASE: (+1, 0, MovementType.ADJUSTMENT),
    AdjustmentKind.DECREASE: (-1, 0, MovementType.ADJUSTMENT),
    AdjustmentKind.DAMAGE: (0, +1, MovementType.DAMAGE),
    AdjustmentKind.RESTORE: (0, -1, MovementType.RESTORE),
    AdjustmentKind.WRITE_OFF: (-1, -1, MovementType.WRITE_OFF),
}


class InventoryService:
    def __init__(self, db: Session, *, update_alerts: bool = True) -> None:
        """`update_alerts=False` is for bulk loading (seed data): the caller evaluates
        alerts (and backorders) once at the end instead of after every operation."""
        self.db = db
        self.update_alerts = update_alerts
        self.repo = InventoryRepository(db)
        self.audit = AuditService(db)

    # ---------------------------------------------------------------- receive
    def receive(self, data: ReceiveRequest, *, user: User | None) -> StockOperationResult:
        """Put received goods into a bin (on_hand +). Checks the bin's capacity."""
        product = self.get_product(data.product_id)
        bin_ = self.get_bin(data.bin_id)
        self._check_fits(product, bin_, data.quantity)

        row = self.repo.get_or_create_row(product.id, bin_.id)
        before = _quantities(row)
        movement = self.change(
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
        self.commit()
        logger.info("Received %s x %s into %s", data.quantity, product.sku, bin_.location_code)
        return StockOperationResult(inventory=row, movements=[movement])

    # ------------------------------------------------------------- adjustments
    def adjust(self, data: AdjustmentRequest, *, user: User | None) -> StockOperationResult:
        """Apply a correction immediately (the adjustment document is stored as completed).

        Who may adjust without approval is decided by the API (manager approval comes in
        a later step); the service only guarantees the stock rules.
        """
        product = self.get_product(data.product_id, allow_archived=True)
        bin_ = self.get_bin(data.bin_id, allow_archived=True)
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
        self.commit()
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
        movement = self.change(
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

    # ------------------------------------------------------------ reservations
    def reserve(self, data: ReserveRequest, *, user: User | None) -> ReservationResult:
        """Hold `quantity` available units, all or nothing.

        A given bin must have enough available units itself; without a bin, units are
        taken from the best bins first (see `rows_with_available_stock`).
        """
        product = self.get_product(data.product_id)
        if data.bin_id is not None:
            bin_ = self.get_bin(data.bin_id)
            row = self.repo.get_row(product.id, bin_.id)
            available = row.quantity_available if row else 0
            if available < data.quantity:
                raise InsufficientStockError(
                    f"Only {available} units of {product.sku} available in {bin_.location_code}"
                )
            plan = [(row, data.quantity)]
        else:
            plan = self._allocate(product, data.quantity)

        reference = (
            (data.reference_type, data.reference_id) if data.reference_type is not None else None
        )
        try:
            result = self._create_reservations(
                product, plan, reference=reference, reason=data.reason, user=user
            )
        except Exception:
            self.db.rollback()
            raise
        self.commit()
        return result

    def reserve_available(
        self,
        product: Product,
        quantity: int,
        *,
        reference: tuple[ReferenceType, int],
        warehouse_id: int | None,
        user: User | None,
        reason: str | None = None,
    ) -> ReservationResult:
        """Hold up to `quantity` units, as many as are available now (no commit).

        Used for orders: what cannot be reserved yet stays backordered. Bins are chosen
        like in `reserve` (picking zones first, then racks closest to packing).
        """
        plan = self._plan(product, quantity, warehouse_id=warehouse_id)
        return self._create_reservations(
            product, plan, reference=reference, reason=reason, user=user
        )

    def _create_reservations(
        self,
        product: Product,
        plan: list[tuple[Inventory, int]],
        *,
        reference: tuple[ReferenceType, int] | None,
        reason: str | None,
        user: User | None,
    ) -> ReservationResult:
        """One reservation (and RESERVATION movement) per planned bin (no commit)."""
        result = ReservationResult(reservations=[], movements=[])
        for row, quantity in plan:
            reservation = self.repo.add(
                StockReservation(
                    product_id=product.id,
                    bin_id=row.bin_id,
                    quantity=quantity,
                    status=ReservationStatus.ACTIVE,
                    reference_type=reference[0] if reference else None,
                    reference_id=reference[1] if reference else None,
                    reason=reason,
                    created_by_id=user.id if user else None,
                )
            )
            self.db.flush()
            before = _quantities(row)
            result.movements.append(
                self.change(
                    row,
                    MovementType.RESERVATION,
                    quantity,
                    reserved=quantity,
                    reference=(ReferenceType.RESERVATION, reservation.id),
                    reason=reason,
                    user=user,
                )
            )
            self.audit.record(
                "inventory.reserve",
                AUDIT_ENTITY,
                row.id,
                summary=(
                    f"Reserved {quantity} x {product.sku} in {row.bin.location_code}"
                    + _for_reference(reference)
                ),
                changes=_diff(before, row),
                actor=user,
            )
            result.reservations.append(reservation)
        return result

    def release(
        self, reservation_id: int, data: ReleaseRequest | None = None, *, user: User | None
    ) -> StockReservation:
        """Cancel an active reservation: its units become available again."""
        reservation = self.repo.get_reservation(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError()
        try:
            self._close_reservation(
                reservation,
                ReservationStatus.RELEASED,
                reason=data.reason if data else None,
                user=user,
            )
        except Exception:
            self.db.rollback()
            raise
        self.commit()
        return reservation

    def release_for_reference(
        self, reference_type: ReferenceType, reference_id: int, *, user: User | None, reason: str
    ) -> list[StockReservation]:
        """Release everything held for e.g. an order (used when an order is cancelled)."""
        reservations = list(self.repo.active_reservations_for(reference_type, reference_id))
        try:
            for reservation in reservations:
                self._close_reservation(
                    reservation, ReservationStatus.RELEASED, reason=reason, user=user
                )
        except Exception:
            self.db.rollback()
            raise
        self.commit()
        return reservations

    def _close_reservation(
        self,
        reservation: StockReservation,
        status: ReservationStatus,
        *,
        reason: str | None,
        user: User | None,
    ) -> InventoryMovement:
        if reservation.status != ReservationStatus.ACTIVE:
            raise ConflictError(f"Reservation {reservation.id} is already {reservation.status}")
        row = self.repo.get_row(reservation.product_id, reservation.bin_id)
        if row is None:  # cannot happen while the database rules hold
            raise ConflictError(f"Reservation {reservation.id} has no stock row")
        before = _quantities(row)
        movement = self.change(
            row,
            MovementType.RELEASE,
            reservation.quantity,
            reserved=-reservation.quantity,
            reference=(ReferenceType.RESERVATION, reservation.id),
            reason=reason,
            user=user,
        )
        reservation.status = status
        reservation.closed_at = datetime.now(UTC)
        self.audit.record(
            "inventory.release",
            AUDIT_ENTITY,
            row.id,
            summary=(
                f"Released reservation {reservation.id}: {reservation.quantity} x "
                f"{row.product.sku} in {row.bin.location_code}"
            ),
            changes=_diff(before, row),
            actor=user,
        )
        return movement

    def consume_reservation(
        self,
        reservation: StockReservation,
        picked: int,
        *,
        reference: tuple[ReferenceType, int],
        reason: str,
        user: User | None,
    ) -> list[InventoryMovement]:
        """A reservation was picked: picked units leave the bin, the rest is released.

        PICK movement: on_hand -picked, reserved -picked (referencing the order).
        RELEASE movement for units that were reserved but not picked. No commit.
        """
        if reservation.status != ReservationStatus.ACTIVE:
            raise ConflictError(f"Reservation {reservation.id} is already {reservation.status}")
        if not 0 <= picked <= reservation.quantity:
            raise UnprocessableError(f"Between 0 and {reservation.quantity} units can be picked")
        row = self.repo.get_row(reservation.product_id, reservation.bin_id)
        if row is None:  # cannot happen while the database rules hold
            raise ConflictError(f"Reservation {reservation.id} has no stock row")
        before = _quantities(row)
        movements = []
        if picked:
            movements.append(
                self.change(
                    row,
                    MovementType.PICK,
                    picked,
                    on_hand=-picked,
                    reserved=-picked,
                    reference=reference,
                    reason=reason,
                    user=user,
                )
            )
        not_picked = reservation.quantity - picked
        if not_picked:
            movements.append(
                self.change(
                    row,
                    MovementType.RELEASE,
                    not_picked,
                    reserved=-not_picked,
                    reference=(ReferenceType.RESERVATION, reservation.id),
                    reason=f"{reason}: {not_picked} not picked",
                    user=user,
                )
            )
        reservation.status = ReservationStatus.FULFILLED if picked else ReservationStatus.RELEASED
        reservation.closed_at = datetime.now(UTC)
        self.audit.record(
            "inventory.pick",
            AUDIT_ENTITY,
            row.id,
            summary=(
                f"Picked {picked} of {reservation.quantity} x {row.product.sku} from "
                f"{row.bin.location_code}{_for_reference(reference)}"
            ),
            changes=_diff(before, row),
            actor=user,
        )
        return movements

    def _allocate(self, product: Product, quantity: int) -> list[tuple[Inventory, int]]:
        """Split `quantity` over the best bins; refuse if there is not enough in total."""
        plan = self._plan(product, quantity)
        total = sum(take for _, take in plan)
        if total < quantity:
            available = sum(
                r.quantity_available for r in self.repo.rows_with_available_stock(product.id)
            )
            raise InsufficientStockError(f"Only {available} units of {product.sku} available")
        return plan

    def _plan(
        self, product: Product, quantity: int, *, warehouse_id: int | None = None
    ) -> list[tuple[Inventory, int]]:
        """Take up to `quantity` units from the best bins (may be fewer)."""
        rows = self.repo.rows_with_available_stock(product.id, warehouse_id)
        plan: list[tuple[Inventory, int]] = []
        remaining = quantity
        for row in rows:
            take = min(row.quantity_available, remaining)
            plan.append((row, take))
            remaining -= take
            if remaining == 0:
                break
        return plan

    # --------------------------------------------------------------- transfers
    def transfer(self, data: TransferRequest, *, user: User | None) -> TransferResult:
        """Move available units to another bin immediately (stored as a completed transfer)."""
        product = self.get_product(data.product_id, allow_archived=True)
        from_bin = self.get_bin(data.from_bin_id, allow_archived=True)
        to_bin = self.get_bin(data.to_bin_id)
        now = datetime.now(UTC)
        transfer = self.repo.add(
            StockTransfer(
                product_id=product.id,
                from_bin_id=from_bin.id,
                to_bin_id=to_bin.id,
                quantity=data.quantity,
                reason=data.reason,
                status=DocumentStatus.COMPLETED,
                requested_by_id=user.id if user else None,
                decided_by_id=user.id if user else None,
                decided_at=now,
            )
        )
        try:
            self.db.flush()
            result = self.apply_transfer(transfer, user=user)
        except Exception:
            self.db.rollback()
            raise
        self.commit()
        return result

    def apply_transfer(self, transfer: StockTransfer, *, user: User | None) -> TransferResult:
        """Move the units as `transfer` says (no commit; also used for approvals).

        Only available units move: reserved and damaged units stay where they are.
        The total quantity of the product is the same before and after.
        """
        product = self.get_product(transfer.product_id, allow_archived=True)
        from_bin = self.get_bin(transfer.from_bin_id, allow_archived=True)
        to_bin = self.get_bin(transfer.to_bin_id)  # never into an archived bin
        quantity = transfer.quantity

        source = self.repo.get_row(product.id, from_bin.id)
        available = source.quantity_available if source else 0
        if available < quantity:
            raise InsufficientStockError(
                f"Only {available} units of {product.sku} available in {from_bin.location_code}"
            )
        # Archived products may still be moved (e.g. to clear a bin); capacity still applies.
        self._check_fits(product, to_bin, quantity, ignore_archived_product=True)
        target = self.repo.get_or_create_row(product.id, to_bin.id)

        reference = (ReferenceType.TRANSFER, transfer.id)
        before_source, before_target = _quantities(source), _quantities(target)
        movements = [
            self.change(
                source,
                MovementType.TRANSFER_OUT,
                quantity,
                on_hand=-quantity,
                reference=reference,
                reason=transfer.reason,
                user=user,
            ),
            self.change(
                target,
                MovementType.TRANSFER_IN,
                quantity,
                on_hand=quantity,
                reference=reference,
                reason=transfer.reason,
                user=user,
            ),
        ]
        self.audit.record(
            "inventory.transfer",
            "stock_transfer",
            transfer.id,
            summary=(
                f"Moved {quantity} x {product.sku} from {from_bin.location_code} "
                f"to {to_bin.location_code}"
            ),
            changes={
                from_bin.location_code: _diff(before_source, source)["quantity_on_hand"],
                to_bin.location_code: _diff(before_target, target)["quantity_on_hand"],
            },
            actor=user,
        )
        return TransferResult(transfer=transfer, source=source, target=target, movements=movements)

    # ------------------------------------------------------- the one way to change
    def change(
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
        # Remember what changed; alerts for it are re-evaluated just before the commit.
        touched = self.db.info.setdefault(TOUCHED_KEY, set())
        touched.add((row.product_id, row.bin_id))
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
    def get_product(self, product_id: int, *, allow_archived: bool = False) -> Product:
        product = self.db.get(Product, product_id)
        if product is None:
            raise UnprocessableError("Product not found")
        if not allow_archived and not product.is_active:
            raise UnprocessableError(f"Product {product.sku} is archived")
        return product

    def get_bin(self, bin_id: int, *, allow_archived: bool = False) -> Bin:
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

    def _check_fits(
        self, product: Product, bin_: Bin, quantity: int, *, ignore_archived_product: bool = False
    ) -> None:
        weight, volume = self.bin_load(bin_.id)
        check = product_fits_bin(
            product, bin_, quantity, current_weight_kg=weight, current_volume_cm3=volume
        )
        reasons = [
            reason
            for reason in check.reasons
            if not (ignore_archived_product and reason == "Product is archived")
        ]
        if reasons:
            raise CapacityExceededError(
                f"{quantity} x {product.sku} do not fit into {bin_.location_code}: "
                + "; ".join(reasons)
            )

    def bin_load(self, bin_id: int) -> tuple[Decimal, Decimal]:
        """Total weight (kg) and volume (cm³) of everything in a bin, damaged units too."""
        rows: Sequence[Inventory] = self.repo.rows_in_bin(bin_id)
        weight = sum((r.product.weight_kg * r.quantity_on_hand for r in rows), Decimal("0"))
        volume = sum((r.product.volume_cm3 * r.quantity_on_hand for r in rows), Decimal("0"))
        return weight, volume

    def commit(self) -> None:
        """Commit the operation, after filling backorders and updating alerts.

        Any stock change may free units for orders waiting for them (backorders), so those
        are retried first, in the same transaction; then low-stock and over-capacity
        alerts are evaluated for everything that changed.
        """
        touched = self.db.info.pop(TOUCHED_KEY, set())
        try:
            if touched and self.update_alerts:
                from app.services.allocation_service import AllocationService  # import cycle

                AllocationService(self.db).retry_backorders(p for p, _ in touched)
                touched |= self.db.info.pop(TOUCHED_KEY, set())
            if touched and self.update_alerts:
                AlertService(self.db).evaluate(
                    product_ids=[product_id for product_id, _ in touched],
                    bin_ids=[bin_id for _, bin_id in touched],
                )
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


def _for_reference(reference: tuple[ReferenceType, int] | None) -> str:
    return f" for {reference[0].value} {reference[1]}" if reference else ""


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
