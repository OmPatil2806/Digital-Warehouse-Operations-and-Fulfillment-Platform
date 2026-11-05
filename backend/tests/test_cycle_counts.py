"""Tests for cycle counts (count a bin, approve the differences)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, PermissionDeniedError, UnprocessableError
from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.inventory import CycleCountStatus, InventoryMovement, MovementType
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    CycleCountRecord,
    CycleCountStart,
    ReceiveRequest,
    ReserveRequest,
)
from app.services.cycle_count_service import CycleCountNotFoundError, CycleCountService
from app.services.inventory_service import InsufficientStockError, InventoryService
from tests.factories import create_bin, create_category, create_product, create_user


@pytest.fixture()
def products(db_session: Session) -> list[Product]:
    category = create_category(db_session)
    return [create_product(db_session, category, sku=f"SKU-{i}") for i in (1, 2, 3)]


@pytest.fixture()
def bin_(db_session: Session) -> Bin:
    return create_bin(db_session)


@pytest.fixture()
def users(db_session: Session) -> dict[str, User]:
    return {
        "staff": create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,)),
        "manager": create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,)),
        "manager2": create_user(db_session, "m2@example.com", roles=(RoleName.MANAGER,)),
    }


@pytest.fixture()
def service(db_session: Session) -> CycleCountService:
    return CycleCountService(db_session)


@pytest.fixture()
def stocked(db_session: Session, products: list[Product], bin_: Bin) -> None:
    """SKU-1: 10 and SKU-2: 5 in the bin; SKU-3 is not there."""
    inventory = InventoryService(db_session)
    for product, quantity in ((products[0], 10), (products[1], 5)):
        inventory.receive(
            ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
        )


def counted(*pairs: tuple[Product, int]) -> CycleCountRecord:
    return CycleCountRecord(lines=[{"product_id": p.id, "counted_quantity": q} for p, q in pairs])


def on_hand(db: Session, product: Product, bin_: Bin) -> int:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    if row is None:
        return 0
    db.refresh(row)
    return row.quantity_on_hand


def count_movements(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(InventoryMovement))


def test_start_records_what_the_system_expects(
    db_session: Session, service: CycleCountService, products, bin_, users, stocked
):
    count = service.start(CycleCountStart(bin_id=bin_.id, note="Weekly"), user=users["staff"])

    assert count.status == CycleCountStatus.OPEN
    assert count.requested_by_id == users["staff"].id
    assert [
        (line.product_id, line.expected_quantity, line.counted_quantity) for line in count.lines
    ] == [
        (products[0].id, 10, None),
        (products[1].id, 5, None),
    ]
    assert db_session.scalar(
        select(AuditLog.summary).where(AuditLog.action == "cycle_count.start")
    ) == ("Started counting WH01-ZA-R01-S01-B01")


def test_a_bin_can_only_have_one_unfinished_count(service: CycleCountService, bin_, users, stocked):
    first = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])

    with pytest.raises(ConflictError, match=f"already being counted \\({first.id}\\)"):
        service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])

    service.cancel(first.id, user=users["staff"])
    service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])  # allowed again


def test_full_count_corrects_the_stock(
    db_session: Session, service: CycleCountService, products, bin_, users, stocked
):
    staff, manager = users["staff"], users["manager"]
    count = service.start(CycleCountStart(bin_id=bin_.id), user=staff)
    # 2 units of SKU-1 missing, SKU-2 correct, 4 units of SKU-3 found that nobody expected
    service.record(
        count.id, counted((products[0], 8), (products[1], 5), (products[2], 4)), user=staff
    )
    service.submit(count.id, user=staff)
    movements = count_movements(db_session)

    service.approve(count.id, approver=manager, note="Looks right")

    assert count.status == CycleCountStatus.COMPLETED
    assert (count.decided_by_id, count.decision_note) == (manager.id, "Looks right")
    assert [on_hand(db_session, p, bin_) for p in products] == [8, 5, 4]
    new = list(
        db_session.scalars(
            select(InventoryMovement).order_by(InventoryMovement.id).offset(movements)
        )
    )
    assert [(m.product_id, m.on_hand_delta, m.quantity) for m in new] == [
        (products[0].id, -2, 2),
        (products[2].id, 4, 4),
    ]  # no movement where nothing differed
    assert {m.movement_type for m in new} == {MovementType.CYCLE_COUNT}
    assert {(m.reference_type, m.reference_id) for m in new} == {("cycle_count", count.id)}
    assert new[0].reason == f"Cycle count {count.id}: expected 10, counted 8"
    assert new[0].created_by_id == manager.id
    approved = db_session.scalar(select(AuditLog).where(AuditLog.action == "cycle_count.approve"))
    assert approved.summary == f"Count {count.id} approved: SKU-1 -2, SKU-3 +4"


def test_counts_can_be_corrected_while_open(
    service: CycleCountService, products, bin_, users, stocked
):
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])
    service.record(count.id, counted((products[0], 7)), user=users["staff"])
    service.record(count.id, counted((products[0], 9)), user=users["staff"])

    assert count.lines[0].counted_quantity == 9
    assert count.lines[0].variance == -1


def test_every_product_must_be_counted_before_submitting(
    service: CycleCountService, products, bin_, users, stocked
):
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])
    service.record(count.id, counted((products[0], 10)), user=users["staff"])

    with pytest.raises(UnprocessableError, match="1 product\\(s\\) have not been counted"):
        service.submit(count.id, user=users["staff"])


def test_differences_are_applied_to_todays_stock(
    db_session: Session, service: CycleCountService, products, bin_, users, stocked
):
    """Stock that moved after the count started stays correct in the history."""
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])
    service.record(count.id, counted((products[0], 9), (products[1], 5)), user=users["staff"])
    service.submit(count.id, user=users["staff"])
    # 3 more units of SKU-1 arrive before the manager approves
    InventoryService(db_session).receive(
        ReceiveRequest(product_id=products[0].id, bin_id=bin_.id, quantity=3), user=None
    )

    service.approve(count.id, approver=users["manager"])

    assert on_hand(db_session, products[0], bin_) == 12  # 10 + 3 received - 1 missing


def test_correction_below_reserved_stock_is_refused(
    db_session: Session, service: CycleCountService, products, bin_, users, stocked
):
    InventoryService(db_session).reserve(
        ReserveRequest(product_id=products[1].id, bin_id=bin_.id, quantity=4), user=None
    )
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])
    # SKU-1's correction is fine, SKU-2's (5 -> 2) would leave fewer than the 4 reserved.
    service.record(count.id, counted((products[0], 8), (products[1], 2)), user=users["staff"])
    service.submit(count.id, user=users["staff"])
    movements = count_movements(db_session)

    with pytest.raises(InsufficientStockError, match="4 reserved"):
        service.approve(count.id, approver=users["manager"])

    # All or nothing: SKU-1 was not corrected either, not even after a later save.
    service.reject(count.id, approver=users["manager"], note="Count SKU-2 again")
    assert count_movements(db_session) == movements
    assert on_hand(db_session, products[0], bin_) == 10
    assert on_hand(db_session, products[1], bin_) == 5
    assert count.status == CycleCountStatus.OPEN


def test_reject_sends_the_count_back(
    db_session: Session, service: CycleCountService, products, bin_, users, stocked
):
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["staff"])
    service.record(count.id, counted((products[0], 1), (products[1], 5)), user=users["staff"])
    service.submit(count.id, user=users["staff"])

    service.reject(count.id, approver=users["manager"], note="9 missing? Please count again")

    assert count.status == CycleCountStatus.OPEN
    assert count.submitted_at is None
    assert count.decision_note == "9 missing? Please count again"
    assert on_hand(db_session, products[0], bin_) == 10
    service.record(count.id, counted((products[0], 10)), user=users["staff"])
    service.submit(count.id, user=users["staff"])
    service.approve(count.id, approver=users["manager"])
    assert on_hand(db_session, products[0], bin_) == 10


def test_who_may_approve_and_cancel(service: CycleCountService, products, bin_, users, stocked):
    count = service.start(CycleCountStart(bin_id=bin_.id), user=users["manager"])
    service.record(count.id, counted((products[0], 10), (products[1], 5)), user=users["manager"])

    with pytest.raises(ConflictError, match="is open, not submitted"):
        service.approve(count.id, approver=users["manager2"])
    service.submit(count.id, user=users["manager"])

    with pytest.raises(PermissionDeniedError, match="Only managers and admins"):
        service.approve(count.id, approver=users["staff"])
    with pytest.raises(PermissionDeniedError, match="a count you started"):
        service.approve(count.id, approver=users["manager"])
    with pytest.raises(PermissionDeniedError, match="Only the person who started"):
        service.cancel(count.id, user=users["staff"])

    service.approve(count.id, approver=users["manager2"])
    with pytest.raises(ConflictError, match="already completed"):
        service.cancel(count.id, user=users["manager"])
    with pytest.raises(ConflictError, match="is completed, not open"):
        service.record(count.id, counted((products[0], 1)), user=users["manager"])


def test_unknown_count_and_invalid_entries(service: CycleCountService, users):
    with pytest.raises(CycleCountNotFoundError):
        service.get(9999)
    with pytest.raises(ValidationError, match="only once"):
        CycleCountRecord(
            lines=[
                {"product_id": 1, "counted_quantity": 1},
                {"product_id": 1, "counted_quantity": 2},
            ]
        )
    with pytest.raises(ValidationError):
        CycleCountRecord(lines=[{"product_id": 1, "counted_quantity": -1}])
    with pytest.raises(ValidationError):
        CycleCountRecord(lines=[])
