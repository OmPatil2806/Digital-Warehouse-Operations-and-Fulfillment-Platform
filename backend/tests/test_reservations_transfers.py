"""Tests for reservations (reserve / release) and transfers between bins."""

import random
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, UnprocessableError
from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.inventory import (
    AdjustmentKind,
    DocumentStatus,
    InventoryMovement,
    MovementType,
    ReferenceType,
    ReservationStatus,
    StockReservation,
    StockTransfer,
)
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    AdjustmentRequest,
    ReceiveRequest,
    ReleaseRequest,
    ReserveRequest,
    TransferRequest,
)
from app.services.inventory_service import (
    CapacityExceededError,
    InsufficientStockError,
    InventoryService,
    ReservationNotFoundError,
)
from tests.factories import create_bin, create_category, create_product, user_with_role


@pytest.fixture()
def product(db_session: Session) -> Product:
    return create_product(db_session, create_category(db_session), sku="LAP-001")  # 1 kg


@pytest.fixture()
def service(db_session: Session) -> InventoryService:
    return InventoryService(db_session)


@pytest.fixture()
def staff(db_session: Session) -> User:
    return user_with_role(db_session, RoleName.STAFF)


@pytest.fixture()
def bin_a(db_session: Session) -> Bin:
    return create_bin(db_session, "WH01-ZA-R01-S01-B01")


@pytest.fixture()
def bin_b(db_session: Session) -> Bin:
    return create_bin(db_session, "WH01-ZA-R01-S01-B02", max_weight_kg="10.000")


def receive(service: InventoryService, product: Product, bin_: Bin, quantity: int) -> None:
    service.receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
    )


def damage(service: InventoryService, product: Product, bin_: Bin, quantity: int) -> None:
    service.adjust(
        AdjustmentRequest(
            product_id=product.id,
            bin_id=bin_.id,
            kind=AdjustmentKind.DAMAGE,
            quantity=quantity,
            reason="Broken",
        ),
        user=None,
    )


def stock(db: Session, product: Product, bin_: Bin) -> tuple[int, int, int]:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    if row is None:
        return (0, 0, 0)
    db.refresh(row)
    return row.quantity_on_hand, row.quantity_reserved, row.quantity_damaged


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


def total_on_hand(db: Session, product: Product) -> int:
    rows = db.scalars(
        select(InventoryMovement.on_hand_delta).where(InventoryMovement.product_id == product.id)
    )
    return sum(rows)


# ------------------------------------------------------------------- reservations
def test_reserve_in_a_bin(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, staff: User
):
    receive(service, product, bin_a, 10)

    result = service.reserve(
        ReserveRequest(
            product_id=product.id,
            bin_id=bin_a.id,
            quantity=4,
            reference_type=ReferenceType.ORDER,
            reference_id=42,
        ),
        user=staff,
    )

    assert stock(db_session, product, bin_a) == (10, 4, 0)  # on hand unchanged, 6 available
    [reservation] = result.reservations
    assert (reservation.status, reservation.quantity) == (ReservationStatus.ACTIVE, 4)
    assert (reservation.reference_type, reservation.reference_id) == ("order", 42)
    assert reservation.created_by_id == staff.id
    [movement] = result.movements
    assert movement.movement_type == MovementType.RESERVATION
    assert (movement.reserved_delta, movement.on_hand_delta, movement.reserved_after) == (4, 0, 4)
    assert (movement.reference_type, movement.reference_id) == ("reservation", reservation.id)
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "inventory.reserve"))
    assert audit.summary == "Reserved 4 x LAP-001 in WH01-ZA-R01-S01-B01 for order 42"
    assert audit.actor_id == staff.id


def test_cannot_reserve_more_than_available(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin
):
    receive(service, product, bin_a, 10)
    damage(service, product, bin_a, 3)
    service.reserve(ReserveRequest(product_id=product.id, bin_id=bin_a.id, quantity=5), user=None)
    movements = count(db_session, InventoryMovement)

    # 10 on hand - 5 reserved - 3 damaged = 2 available
    with pytest.raises(InsufficientStockError, match="Only 2 units of LAP-001 available in WH01"):
        service.reserve(
            ReserveRequest(product_id=product.id, bin_id=bin_a.id, quantity=3), user=None
        )
    with pytest.raises(InsufficientStockError, match="Only 2 units of LAP-001 available"):
        service.reserve(ReserveRequest(product_id=product.id, quantity=3), user=None)

    assert stock(db_session, product, bin_a) == (10, 5, 3)
    assert count(db_session, StockReservation) == 1
    assert count(db_session, InventoryMovement) == movements


def test_reserving_in_an_empty_bin(service: InventoryService, product: Product, bin_a: Bin):
    with pytest.raises(InsufficientStockError, match="Only 0 units"):
        service.reserve(
            ReserveRequest(product_id=product.id, bin_id=bin_a.id, quantity=1), user=None
        )


def test_automatic_reservation_takes_the_best_bins_first(
    db_session: Session, service: InventoryService, product: Product
):
    bulk = create_bin(db_session, "WH01-ZB-R01-S01-B01")
    far = create_bin(db_session, "WH01-ZA-R09-S01-B01")
    near = create_bin(db_session, "WH01-ZA-R01-S01-B01")
    empty = create_bin(db_session, "WH01-ZA-R00-S01-B01")
    bulk.shelf.rack.zone.zone_type = "bulk"
    bulk.shelf.rack.distance_to_packing_m = Decimal("1.0")  # close, but bulk storage
    far.shelf.rack.distance_to_packing_m = Decimal("40.0")
    near.shelf.rack.distance_to_packing_m = Decimal("5.0")
    db_session.commit()
    for bin_, quantity in ((bulk, 50), (far, 10), (near, 3)):
        receive(service, product, bin_, quantity)

    result = service.reserve(ReserveRequest(product_id=product.id, quantity=20), user=None)

    taken = [(r.bin_id, r.quantity) for r in result.reservations]
    assert taken == [(near.id, 3), (far.id, 10), (bulk.id, 7)]
    assert result.quantity == 20
    assert stock(db_session, product, empty) == (0, 0, 0)


def test_automatic_reservation_skips_archived_bins(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    receive(service, product, bin_a, 5)
    receive(service, product, bin_b, 5)
    bin_a.is_active = False
    db_session.commit()

    with pytest.raises(InsufficientStockError, match="Only 5 units"):
        service.reserve(ReserveRequest(product_id=product.id, quantity=6), user=None)
    result = service.reserve(ReserveRequest(product_id=product.id, quantity=5), user=None)
    assert [r.bin_id for r in result.reservations] == [bin_b.id]


def test_archived_products_cannot_be_reserved(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin
):
    receive(service, product, bin_a, 5)
    product.is_active = False
    db_session.commit()

    with pytest.raises(UnprocessableError, match="archived"):
        service.reserve(ReserveRequest(product_id=product.id, quantity=1), user=None)


def test_release_makes_units_available_again(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, staff: User
):
    receive(service, product, bin_a, 10)
    [reservation] = service.reserve(
        ReserveRequest(product_id=product.id, bin_id=bin_a.id, quantity=4), user=None
    ).reservations

    service.release(reservation.id, ReleaseRequest(reason="Customer cancelled"), user=staff)

    assert stock(db_session, product, bin_a) == (10, 0, 0)
    assert reservation.status == ReservationStatus.RELEASED
    assert reservation.closed_at is not None
    last = db_session.scalars(
        select(InventoryMovement).order_by(InventoryMovement.id.desc())
    ).first()
    assert (last.movement_type, last.reserved_delta, last.reason) == (
        MovementType.RELEASE,
        -4,
        "Customer cancelled",
    )
    assert last.created_by_id == staff.id

    with pytest.raises(ConflictError, match="already released"):
        service.release(reservation.id, user=None)
    with pytest.raises(ReservationNotFoundError):
        service.release(99999, user=None)


def test_release_everything_held_for_an_order(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    receive(service, product, bin_a, 2)
    receive(service, product, bin_b, 5)
    order = {"reference_type": ReferenceType.ORDER, "reference_id": 7}
    service.reserve(ReserveRequest(product_id=product.id, quantity=6, **order), user=None)
    service.reserve(
        ReserveRequest(product_id=product.id, quantity=1, reference_type="order", reference_id=8),
        user=None,
    )

    released = service.release_for_reference(
        ReferenceType.ORDER, 7, user=None, reason="Order cancelled"
    )

    assert sorted(r.quantity for r in released) == [2, 4]
    assert stock(db_session, product, bin_a) == (2, 0, 0)
    assert stock(db_session, product, bin_b) == (5, 1, 0)  # order 8 is still held


def test_reservation_reference_must_be_complete():
    with pytest.raises(ValidationError, match="given together"):
        ReserveRequest(product_id=1, quantity=1, reference_type="order")


# ---------------------------------------------------------------------- transfers
def test_transfer_moves_units_and_keeps_the_total(
    db_session: Session,
    service: InventoryService,
    product: Product,
    bin_a: Bin,
    bin_b: Bin,
    staff: User,
):
    receive(service, product, bin_a, 10)

    result = service.transfer(
        TransferRequest(
            product_id=product.id,
            from_bin_id=bin_a.id,
            to_bin_id=bin_b.id,
            quantity=4,
            reason="Replenish picking bin",
        ),
        user=staff,
    )

    assert stock(db_session, product, bin_a) == (6, 0, 0)
    assert stock(db_session, product, bin_b) == (4, 0, 0)
    assert total_on_hand(db_session, product) == 10
    assert result.transfer.status == DocumentStatus.COMPLETED
    assert result.transfer.decided_by_id == staff.id
    out, into = result.movements
    assert (out.movement_type, out.bin_id, out.on_hand_delta) == ("transfer_out", bin_a.id, -4)
    assert (into.movement_type, into.bin_id, into.on_hand_delta) == ("transfer_in", bin_b.id, 4)
    assert {(m.reference_type, m.reference_id) for m in result.movements} == {
        ("transfer", result.transfer.id)
    }
    audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "inventory.transfer"))
    assert audit.entity_type == "stock_transfer"
    assert audit.summary == ("Moved 4 x LAP-001 from WH01-ZA-R01-S01-B01 to WH01-ZA-R01-S01-B02")
    assert audit.changes == {
        "WH01-ZA-R01-S01-B01": {"old": 10, "new": 6},
        "WH01-ZA-R01-S01-B02": {"old": 0, "new": 4},
    }


def test_only_available_units_can_be_transferred(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    receive(service, product, bin_a, 10)
    damage(service, product, bin_a, 2)
    service.reserve(ReserveRequest(product_id=product.id, bin_id=bin_a.id, quantity=5), user=None)

    with pytest.raises(InsufficientStockError, match="Only 3 units"):
        service.transfer(
            TransferRequest(
                product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_b.id, quantity=4
            ),
            user=None,
        )
    assert stock(db_session, product, bin_a) == (10, 5, 2)
    assert count(db_session, StockTransfer) == 0


def test_transfer_checks_the_target_capacity(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    receive(service, product, bin_a, 30)
    receive(service, product, bin_b, 8)  # bin_b holds at most 10 kg

    with pytest.raises(CapacityExceededError, match="WH01-ZA-R01-S01-B02"):
        service.transfer(
            TransferRequest(
                product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_b.id, quantity=3
            ),
            user=None,
        )
    assert stock(db_session, product, bin_a) == (30, 0, 0)


def test_transfer_out_of_but_not_into_archived_bins(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    receive(service, product, bin_a, 5)
    bin_a.is_active = False
    db_session.commit()

    def move(source: Bin, target: Bin) -> None:
        service.transfer(
            TransferRequest(
                product_id=product.id, from_bin_id=source.id, to_bin_id=target.id, quantity=1
            ),
            user=None,
        )

    move(bin_a, bin_b)  # emptying an archived bin is fine
    with pytest.raises(UnprocessableError, match="archived"):
        move(bin_b, bin_a)


def test_transfer_needs_two_different_bins():
    with pytest.raises(ValidationError, match="different bins"):
        TransferRequest(product_id=1, from_bin_id=3, to_bin_id=3, quantity=1)


def test_random_transfers_and_reservations_keep_stock_consistent(
    db_session: Session, service: InventoryService, product: Product
):
    """Many random operations: the total never changes through transfers or reservations,
    and the movements always explain the stock of every bin."""
    bins = [create_bin(db_session, f"WH01-ZA-R01-S01-B{i:02d}") for i in range(1, 5)]
    for bin_ in bins:
        receive(service, product, bin_, 25)
    rng = random.Random(7)
    active: list[int] = []
    for _ in range(200):
        try:
            roll = rng.random()
            if roll < 0.5:
                source, target = rng.sample(bins, 2)
                service.transfer(
                    TransferRequest(
                        product_id=product.id,
                        from_bin_id=source.id,
                        to_bin_id=target.id,
                        quantity=rng.randint(1, 15),
                    ),
                    user=None,
                )
            elif roll < 0.8:
                result = service.reserve(
                    ReserveRequest(product_id=product.id, quantity=rng.randint(1, 12)), user=None
                )
                active += [r.id for r in result.reservations]
            elif active:
                service.release(active.pop(rng.randrange(len(active))), user=None)
        except (InsufficientStockError, CapacityExceededError):
            pass
        assert total_on_hand(db_session, product) == 100

    assert count(db_session, StockTransfer) > 20  # the test really moved stock
    for bin_ in bins:
        sums = db_session.execute(
            select(
                func.sum(InventoryMovement.on_hand_delta),
                func.sum(InventoryMovement.reserved_delta),
                func.sum(InventoryMovement.damaged_delta),
            ).where(InventoryMovement.bin_id == bin_.id)
        ).one()
        assert tuple(sums) == stock(db_session, product, bin_)
    held = db_session.scalar(
        select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
            StockReservation.status == ReservationStatus.ACTIVE.value
        )
    )
    assert held == sum(stock(db_session, product, b)[1] for b in bins)


def test_applying_a_waiting_transfer_rechecks_the_bins(
    db_session: Session, service: InventoryService, product: Product, bin_a: Bin, bin_b: Bin
):
    """A transfer request may wait for approval; when it is applied, the rules are checked
    again against the bins as they are *now*."""
    receive(service, product, bin_a, 5)
    waiting = StockTransfer(
        product_id=product.id, from_bin_id=bin_a.id, to_bin_id=bin_b.id, quantity=2
    )
    db_session.add(waiting)
    bin_b.is_active = False  # archived while the request was waiting
    db_session.commit()

    with pytest.raises(UnprocessableError, match="archived"):
        service.apply_transfer(waiting, user=None)
