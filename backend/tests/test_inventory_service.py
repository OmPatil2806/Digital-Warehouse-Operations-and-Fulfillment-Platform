"""Tests for receiving and adjustments (InventoryService)."""

import random

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.exceptions import UnprocessableError
from app.models.audit import AuditLog
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
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import AdjustmentRequest, ReceiveRequest
from app.services.inventory_service import (
    CapacityExceededError,
    InsufficientStockError,
    InventoryService,
    StockChangedError,
)
from tests.factories import create_bin, create_category, create_product, user_with_role


@pytest.fixture()
def product(db_session: Session) -> Product:
    # 1 kg, 10 x 10 x 10 cm = 1000 cm³ per unit
    return create_product(db_session, create_category(db_session), sku="LAP-001")


@pytest.fixture()
def bin_(db_session: Session) -> Bin:
    # room for 10 units by weight, 20 by volume
    return create_bin(db_session, max_weight_kg="10.000", max_volume_cm3=20_000)


@pytest.fixture()
def staff(db_session: Session) -> User:
    return user_with_role(db_session, RoleName.STAFF)


@pytest.fixture()
def service(db_session: Session) -> InventoryService:
    return InventoryService(db_session)


def receive(service: InventoryService, product: Product, bin_: Bin, quantity: int, user=None):
    return service.receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=user
    )


def adjust(service, product, bin_, kind: AdjustmentKind, quantity: int, user=None):
    return service.adjust(
        AdjustmentRequest(
            product_id=product.id, bin_id=bin_.id, kind=kind, quantity=quantity, reason="Counted"
        ),
        user=user,
    )


def stock(db: Session, product: Product, bin_: Bin) -> tuple[int, int, int]:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    db.refresh(row)
    return row.quantity_on_hand, row.quantity_reserved, row.quantity_damaged


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ------------------------------------------------------------------------ receive
def test_receive_creates_stock_movement_and_audit_record(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin, staff: User
):
    result = service.receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=4, reason="PO-1001"),
        user=staff,
    )

    assert stock(db_session, product, bin_) == (4, 0, 0)
    assert result.inventory.quantity_available == 4
    [movement] = result.movements
    assert movement.movement_type == MovementType.RECEIPT
    assert (movement.quantity, movement.on_hand_delta, movement.on_hand_after) == (4, 4, 4)
    assert (movement.reason, movement.created_by_id) == ("PO-1001", staff.id)
    assert movement.reference_type is None

    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "inventory.receive"))
    assert audit.entity_id == result.inventory.id
    assert audit.actor_id == staff.id
    assert audit.summary == "Received 4 x LAP-001 into WH01-ZA-R01-S01-B01"
    assert audit.changes == {"quantity_on_hand": {"old": 0, "new": 4}}


def test_receiving_again_adds_to_the_same_row(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 3)
    second = receive(service, product, bin_, 2)

    assert stock(db_session, product, bin_) == (5, 0, 0)
    assert count(db_session, Inventory) == 1
    assert second.movements[0].on_hand_after == 5
    assert second.movements[0].created_by_id is None  # no user = the system


def test_receive_checks_capacity_including_what_is_already_there(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 6)

    with pytest.raises(CapacityExceededError, match="Too heavy: needs 5.000 kg, 4.000 kg"):
        receive(service, product, bin_, 5)
    assert stock(db_session, product, bin_) == (6, 0, 0)
    assert count(db_session, InventoryMovement) == 1


def test_damaged_units_still_take_up_space(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 10)
    adjust(service, product, bin_, AdjustmentKind.DAMAGE, 3)

    with pytest.raises(CapacityExceededError):
        receive(service, product, bin_, 1)


def test_receive_refuses_unknown_or_archived_product_and_bin(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    with pytest.raises(UnprocessableError, match="Product not found"):
        service.receive(ReceiveRequest(product_id=9999, bin_id=bin_.id, quantity=1), user=None)
    with pytest.raises(UnprocessableError, match="Bin not found"):
        service.receive(ReceiveRequest(product_id=product.id, bin_id=9999, quantity=1), user=None)

    bin_.is_active = False
    db_session.commit()
    with pytest.raises(UnprocessableError, match="Bin WH01-ZA-R01-S01-B01 is archived"):
        receive(service, product, bin_, 1)

    bin_.is_active = True
    product.is_active = False
    db_session.commit()
    with pytest.raises(UnprocessableError, match="Product LAP-001 is archived"):
        receive(service, product, bin_, 1)


# ---------------------------------------------------------------------- adjustments
@pytest.mark.parametrize(
    ("kind", "quantity", "expected", "movement_type"),
    [
        (AdjustmentKind.INCREASE, 2, (8, 0, 2), MovementType.ADJUSTMENT),
        (AdjustmentKind.DECREASE, 2, (4, 0, 2), MovementType.ADJUSTMENT),
        (AdjustmentKind.DAMAGE, 1, (6, 0, 3), MovementType.DAMAGE),
        (AdjustmentKind.RESTORE, 1, (6, 0, 1), MovementType.RESTORE),
        (AdjustmentKind.WRITE_OFF, 2, (4, 0, 0), MovementType.WRITE_OFF),
    ],
)
def test_each_adjustment_kind(
    db_session: Session,
    service: InventoryService,
    product: Product,
    bin_: Bin,
    staff: User,
    kind: AdjustmentKind,
    quantity: int,
    expected: tuple[int, int, int],
    movement_type: MovementType,
):
    receive(service, product, bin_, 6)
    adjust(service, product, bin_, AdjustmentKind.DAMAGE, 2)  # start: 6 on hand, 2 damaged

    result = adjust(service, product, bin_, kind, quantity, user=staff)

    assert stock(db_session, product, bin_) == expected
    document = result.adjustment
    assert document.status == DocumentStatus.COMPLETED
    assert (document.requested_by_id, document.decided_by_id) == (staff.id, staff.id)
    assert document.decided_at is not None
    [movement] = result.movements
    assert movement.movement_type == movement_type
    assert (movement.reference_type, movement.reference_id) == (
        ReferenceType.ADJUSTMENT,
        document.id,
    )
    assert movement.reason == "Counted"
    audit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "inventory.adjust").order_by(AuditLog.id.desc())
    ).first()
    assert audit.actor_id == staff.id
    assert "LAP-001 in WH01-ZA-R01-S01-B01 (Counted)" in audit.summary


@pytest.mark.parametrize(
    ("kind", "quantity", "message"),
    [
        # 10 on hand, 2 damaged -> 8 available
        (AdjustmentKind.DECREASE, 9, "Only 8 units available"),
        (AdjustmentKind.DECREASE, 11, "Only 10 units on hand"),
        (AdjustmentKind.DAMAGE, 9, "Only 8 units available"),
        (AdjustmentKind.RESTORE, 3, "Only 2 damaged units"),
        (AdjustmentKind.WRITE_OFF, 3, "Only 2 damaged units"),
    ],
)
def test_stock_can_never_go_negative(
    db_session: Session,
    service: InventoryService,
    product: Product,
    bin_: Bin,
    kind: AdjustmentKind,
    quantity: int,
    message: str,
):
    receive(service, product, bin_, 10)
    adjust(service, product, bin_, AdjustmentKind.DAMAGE, 2)
    movements, adjustments = count(db_session, InventoryMovement), count(
        db_session, StockAdjustment
    )

    with pytest.raises(InsufficientStockError, match=message):
        adjust(service, product, bin_, kind, quantity)

    # A refused operation leaves no trace: stock, movements and documents are unchanged.
    assert stock(db_session, product, bin_) == (10, 0, 2)
    assert count(db_session, InventoryMovement) == movements
    assert count(db_session, StockAdjustment) == adjustments


def test_reserved_units_cannot_be_removed_or_damaged(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 5)
    row = InventoryRepository(db_session).get_row(product.id, bin_.id)
    row.quantity_reserved = 4  # reservations come in the next step
    db_session.commit()

    for kind in (AdjustmentKind.DECREASE, AdjustmentKind.DAMAGE):
        with pytest.raises(InsufficientStockError, match="Only 1 units available"):
            adjust(service, product, bin_, kind, 2)
    adjust(service, product, bin_, AdjustmentKind.DECREASE, 1)
    assert stock(db_session, product, bin_) == (4, 4, 0)


def test_removing_from_an_empty_bin(service: InventoryService, product: Product, bin_: Bin):
    with pytest.raises(InsufficientStockError, match="There is no LAP-001 in WH01-ZA-R01-S01-B01"):
        adjust(service, product, bin_, AdjustmentKind.DECREASE, 1)


def test_archived_products_can_be_cleared_but_not_increased(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 5)
    product.is_active = False
    db_session.commit()

    adjust(service, product, bin_, AdjustmentKind.DECREASE, 5)  # clearing out is fine
    with pytest.raises(UnprocessableError, match="archived"):
        adjust(service, product, bin_, AdjustmentKind.INCREASE, 1)


def test_increase_checks_capacity(
    db_session: Session, service: InventoryService, product: Product, bin_: Bin
):
    receive(service, product, bin_, 9)

    with pytest.raises(CapacityExceededError):
        adjust(service, product, bin_, AdjustmentKind.INCREASE, 2)
    assert count(db_session, StockAdjustment) == 0


def test_adjustments_need_a_reason():
    with pytest.raises(ValidationError):
        AdjustmentRequest(product_id=1, bin_id=1, kind="decrease", quantity=1, reason="  ")
    with pytest.raises(ValidationError):
        ReceiveRequest(product_id=1, bin_id=1, quantity=0)
    with pytest.raises(ValidationError):
        ReceiveRequest(product_id=1, bin_id=1, quantity=1_000_001)


# -------------------------------------------------------------------- concurrency
def test_concurrent_change_is_refused_instead_of_lost(
    db_session: Session,
    service: InventoryService,
    product: Product,
    bin_: Bin,
    monkeypatch: pytest.MonkeyPatch,
):
    receive(service, product, bin_, 5)
    original = InventoryRepository.get_row

    def get_row_then_someone_else_changes_it(self, product_id, bin_id):  # noqa: ANN001, ANN202
        row = original(self, product_id, bin_id)
        self.db.execute(
            text("UPDATE inventory SET quantity_on_hand = 3, version = version + 1 WHERE id = :id"),
            {"id": row.id},
        )
        self.db.commit()  # the other request finished first
        return row

    monkeypatch.setattr(InventoryRepository, "get_row", get_row_then_someone_else_changes_it)
    with pytest.raises(StockChangedError, match="Please try again"):
        adjust(service, product, bin_, AdjustmentKind.DECREASE, 1)
    monkeypatch.undo()

    # The other request's change survives; ours was not applied on top of stale numbers.
    assert stock(db_session, product, bin_) == (3, 0, 0)


# -------------------------------------------------------------------- traceability
def test_every_quantity_is_explained_by_its_movements(
    db_session: Session, service: InventoryService, product: Product
):
    """Random operations; afterwards the sum of all movement deltas equals the stock."""
    bins = [create_bin(db_session, f"WH01-ZA-R01-S01-B0{i}") for i in range(1, 4)]
    rng = random.Random(42)
    kinds = list(AdjustmentKind)
    for _ in range(150):
        target = rng.choice(bins)
        try:
            if rng.random() < 0.4:
                receive(service, product, target, rng.randint(1, 30))
            else:
                adjust(service, product, target, rng.choice(kinds), rng.randint(1, 10))
        except (InsufficientStockError, CapacityExceededError):
            pass  # refused operations must not leave anything behind
    assert count(db_session, InventoryMovement) > 75  # most operations went through

    for target in bins:
        row = InventoryRepository(db_session).get_row(product.id, target.id)
        sums = db_session.execute(
            select(
                func.sum(InventoryMovement.on_hand_delta),
                func.sum(InventoryMovement.reserved_delta),
                func.sum(InventoryMovement.damaged_delta),
            ).where(InventoryMovement.bin_id == target.id)
        ).one()
        assert tuple(sums) == stock(db_session, product, target)
        assert row.quantity_available >= 0
        last = db_session.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.bin_id == target.id)
            .order_by(InventoryMovement.id.desc())
        ).first()
        assert (last.on_hand_after, last.damaged_after) == (
            row.quantity_on_hand,
            row.quantity_damaged,
        )
