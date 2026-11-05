"""Tests for the inventory tables: quantity rules, immutable movements, documents."""

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models.catalog import Product
from app.models.inventory import (
    AdjustmentKind,
    CycleCount,
    CycleCountLine,
    CycleCountStatus,
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
from app.models.warehouse import Bin
from tests.factories import create_bin, create_category, create_product


@pytest.fixture()
def product(db_session: Session) -> Product:
    return create_product(db_session, create_category(db_session))


@pytest.fixture()
def bin_a(db_session: Session) -> Bin:
    return create_bin(db_session, "WH01-ZA-R01-S01-B01")


@pytest.fixture()
def bin_b(db_session: Session) -> Bin:
    return create_bin(db_session, "WH01-ZA-R01-S01-B02")


def add(db: Session, obj: object) -> object:
    db.add(obj)
    db.commit()
    return obj


def expect_integrity_error(db: Session, obj: object, match: str | None = None) -> None:
    db.add(obj)
    with pytest.raises(IntegrityError, match=match):
        db.commit()
    db.rollback()


def movement(product: Product, bin_: Bin, **overrides: object) -> InventoryMovement:
    """A valid receipt of 10 units into an empty bin."""
    values: dict[str, object] = {
        "movement_type": MovementType.RECEIPT,
        "product_id": product.id,
        "bin_id": bin_.id,
        "quantity": 10,
        "on_hand_delta": 10,
        "reserved_delta": 0,
        "damaged_delta": 0,
        "on_hand_after": 10,
        "reserved_after": 0,
        "damaged_after": 0,
    }
    values.update(overrides)
    return InventoryMovement(**values)


# ------------------------------------------------------------------------ inventory
def test_inventory_defaults_and_available(db_session: Session, product: Product, bin_a: Bin):
    row = add(db_session, Inventory(product_id=product.id, bin_id=bin_a.id))
    db_session.expire_all()

    row = db_session.get(Inventory, row.id)
    assert (row.quantity_on_hand, row.quantity_reserved, row.quantity_damaged) == (0, 0, 0)
    assert row.quantity_available == 0
    assert row.version == 1
    assert row.product.sku == product.sku
    assert row.bin.location_code == "WH01-ZA-R01-S01-B01"

    row.quantity_on_hand = 20
    row.quantity_reserved = 5
    row.quantity_damaged = 3
    db_session.commit()
    assert row.quantity_available == 12
    assert row.version == 2  # every update bumps the version


def test_one_inventory_row_per_product_and_bin(
    db_session: Session, product: Product, bin_a: Bin, bin_b: Bin
):
    add(db_session, Inventory(product_id=product.id, bin_id=bin_a.id))
    add(db_session, Inventory(product_id=product.id, bin_id=bin_b.id))  # other bin is fine

    expect_integrity_error(db_session, Inventory(product_id=product.id, bin_id=bin_a.id))


@pytest.mark.parametrize(
    ("on_hand", "reserved", "damaged", "constraint"),
    [
        (-1, 0, 0, "on_hand_not_negative"),
        (5, -1, 0, "reserved_not_negative"),
        (5, 0, -1, "damaged_not_negative"),
        (5, 4, 2, "available_not_negative"),  # 5 - 4 - 2 < 0
    ],
)
def test_inventory_quantities_cannot_go_negative(
    db_session: Session,
    product: Product,
    bin_a: Bin,
    on_hand: int,
    reserved: int,
    damaged: int,
    constraint: str,
):
    expect_integrity_error(
        db_session,
        Inventory(
            product_id=product.id,
            bin_id=bin_a.id,
            quantity_on_hand=on_hand,
            quantity_reserved=reserved,
            quantity_damaged=damaged,
        ),
        match=constraint,
    )


def test_stale_inventory_update_is_refused(db_session: Session, product: Product, bin_a: Bin):
    """Optimistic locking: if another request changed the row since we read it, our update
    fails instead of silently overwriting their change."""
    row = add(db_session, Inventory(product_id=product.id, bin_id=bin_a.id, quantity_on_hand=10))
    # Simulate a concurrent request that changed the row after we loaded it.
    db_session.execute(
        text("UPDATE inventory SET quantity_on_hand = 7, version = version + 1 WHERE id = :id"),
        {"id": row.id},
    )

    row.quantity_on_hand = 12
    with pytest.raises(StaleDataError):
        db_session.flush()
    db_session.rollback()


def test_bin_and_product_with_stock_cannot_be_deleted(
    db_session: Session, product: Product, bin_a: Bin
):
    add(db_session, Inventory(product_id=product.id, bin_id=bin_a.id))

    for statement in (delete(Bin).filter_by(id=bin_a.id), delete(Product).filter_by(id=product.id)):
        with pytest.raises(IntegrityError):
            db_session.execute(statement)
        db_session.rollback()


# ------------------------------------------------------------------------ movements
def test_movement_round_trip(db_session: Session, product: Product, bin_a: Bin):
    saved = add(
        db_session,
        movement(product, bin_a, reference_type=ReferenceType.ADJUSTMENT, reference_id=1),
    )
    db_session.expire_all()

    saved = db_session.get(InventoryMovement, saved.id)
    assert saved.movement_type == MovementType.RECEIPT
    assert saved.created_at.tzinfo is not None
    assert saved.created_by is None  # system movement
    assert saved.bin.location_code == bin_a.location_code


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"movement_type": "teleport"}, "valid_movement_type"),
        ({"quantity": 0}, "quantity_positive"),
        ({"on_hand_delta": 0}, "changes_something"),
        ({"on_hand_after": -1}, "balances_valid"),
        ({"reserved_after": 6, "damaged_after": 5}, "balances_valid"),  # 6 + 5 > 10
        ({"reference_type": "invoice", "reference_id": 1}, "valid_reference_type"),
        ({"reference_type": "transfer"}, "reference_complete"),
        ({"reference_id": 1}, "reference_complete"),
    ],
)
def test_invalid_movements_are_rejected(
    db_session: Session, product: Product, bin_a: Bin, overrides: dict, constraint: str
):
    expect_integrity_error(db_session, movement(product, bin_a, **overrides), match=constraint)


def test_movements_are_immutable(db_session: Session, product: Product, bin_a: Bin):
    saved = add(db_session, movement(product, bin_a))

    statements = [
        update(InventoryMovement).filter_by(id=saved.id).values(quantity=999),
        text("UPDATE inventory_movements SET reason = 'edited'"),
        delete(InventoryMovement).filter_by(id=saved.id),
        text("DELETE FROM inventory_movements"),
    ]
    for statement in statements:
        with pytest.raises(IntegrityError, match="inventory movements are immutable"):
            db_session.execute(statement)
        db_session.rollback()

    # ORM changes are refused too
    saved = db_session.get(InventoryMovement, saved.id)
    saved.reason = "edited"
    with pytest.raises(IntegrityError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    assert db_session.scalar(select(InventoryMovement.quantity).filter_by(id=saved.id)) == 10


# ------------------------------------------------------------------------ documents
def test_transfer_defaults_and_rules(db_session: Session, product: Product, bin_a: Bin, bin_b: Bin):
    transfer = add(
        db_session,
        StockTransfer(product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_b.id, quantity=4),
    )
    assert transfer.status == DocumentStatus.PENDING
    assert transfer.from_bin.code == "B01"
    assert transfer.to_bin.code == "B02"

    expect_integrity_error(
        db_session,
        StockTransfer(product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_a.id, quantity=1),
        match="different_bins",
    )
    expect_integrity_error(
        db_session,
        StockTransfer(product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_b.id, quantity=0),
        match="quantity_positive",
    )
    expect_integrity_error(
        db_session,
        StockTransfer(
            product_id=product.id,
            from_bin_id=bin_a.id,
            to_bin_id=bin_b.id,
            quantity=1,
            status="approved",
        ),
        match="valid_status",
    )


def test_adjustment_needs_a_valid_kind_and_reason(
    db_session: Session, product: Product, bin_a: Bin
):
    adjustment = add(
        db_session,
        StockAdjustment(
            product_id=product.id,
            bin_id=bin_a.id,
            kind=AdjustmentKind.DAMAGE,
            quantity=2,
            reason="Dropped by forklift",
        ),
    )
    assert adjustment.status == DocumentStatus.PENDING

    expect_integrity_error(
        db_session,
        StockAdjustment(
            product_id=product.id, bin_id=bin_a.id, kind="steal", quantity=1, reason="x"
        ),
        match="valid_kind",
    )
    expect_integrity_error(
        db_session,
        StockAdjustment(product_id=product.id, bin_id=bin_a.id, kind="increase", quantity=1),
    )


def test_reservation_defaults_and_reference(db_session: Session, product: Product, bin_a: Bin):
    reservation = add(
        db_session,
        StockReservation(
            product_id=product.id,
            bin_id=bin_a.id,
            quantity=3,
            reference_type=ReferenceType.ORDER,
            reference_id=42,
        ),
    )
    assert reservation.status == ReservationStatus.ACTIVE
    assert reservation.closed_at is None

    expect_integrity_error(
        db_session,
        StockReservation(product_id=product.id, bin_id=bin_a.id, quantity=1, reference_id=42),
        match="reference_complete",
    )


def test_cycle_count_lines_variance_and_cascade(db_session: Session, product: Product, bin_a: Bin):
    other = create_product(db_session, product.category, sku="LAP-002")
    count = CycleCount(bin_id=bin_a.id)
    count.lines = [
        CycleCountLine(product_id=product.id, expected_quantity=10, counted_quantity=8),
        CycleCountLine(product_id=other.id, expected_quantity=5),
    ]
    add(db_session, count)
    db_session.expire_all()

    count = db_session.get(CycleCount, count.id)
    assert count.status == CycleCountStatus.OPEN
    assert [line.variance for line in count.lines] == [-2, None]  # None = not counted yet

    expect_integrity_error(
        db_session,
        CycleCountLine(cycle_count_id=count.id, product_id=product.id, expected_quantity=1),
        match="UNIQUE",
    )

    db_session.execute(delete(CycleCount).filter_by(id=count.id))  # lines go with it
    assert db_session.scalars(select(CycleCountLine)).all() == []
