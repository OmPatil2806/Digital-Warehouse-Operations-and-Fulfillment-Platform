"""Tests for manager approval of transfers and adjustments."""

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, PermissionDeniedError
from app.models.audit import AuditLog
from app.models.catalog import Product
from app.models.inventory import (
    AdjustmentKind,
    DocumentStatus,
    InventoryMovement,
    StockAdjustment,
    StockTransfer,
)
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import AdjustmentRequest, ReceiveRequest, RejectRequest, TransferRequest
from app.services.approval_service import (
    ApprovalService,
    RequestNotFoundError,
    adjustment_needs_approval,
)
from app.services.inventory_service import InsufficientStockError, InventoryService
from tests.factories import create_bin, create_category, create_product, create_user


@pytest.fixture()
def product(db_session: Session) -> Product:
    return create_product(db_session, create_category(db_session), sku="LAP-001")


@pytest.fixture()
def bins(db_session: Session) -> dict[str, Bin]:
    return {
        "a": create_bin(db_session, "WH01-ZA-R01-S01-B01"),
        "b": create_bin(db_session, "WH01-ZA-R01-S01-B02"),
        "other_site": create_bin(db_session, "WH02-ZA-R01-S01-B01"),
    }


@pytest.fixture()
def users(db_session: Session) -> dict[str, User]:
    return {
        "staff": create_user(db_session, "staff@example.com", roles=(RoleName.STAFF,)),
        "staff2": create_user(db_session, "staff2@example.com", roles=(RoleName.STAFF,)),
        "manager": create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,)),
        "admin": create_user(db_session, "admin@example.com", roles=(RoleName.ADMIN,)),
    }


@pytest.fixture()
def service(db_session: Session) -> ApprovalService:
    return ApprovalService(db_session)


@pytest.fixture()
def stocked(db_session: Session, product: Product, bins: dict[str, Bin]) -> None:
    """10 units in bin a."""
    InventoryService(db_session).receive(
        ReceiveRequest(product_id=product.id, bin_id=bins["a"].id, quantity=10), user=None
    )


def adjustment(product: Product, bin_: Bin, kind: AdjustmentKind, quantity: int = 3):
    return AdjustmentRequest(
        product_id=product.id, bin_id=bin_.id, kind=kind, quantity=quantity, reason="Missing"
    )


def transfer(product: Product, source: Bin, target: Bin, quantity: int = 4):
    return TransferRequest(
        product_id=product.id, from_bin_id=source.id, to_bin_id=target.id, quantity=quantity
    )


def on_hand(db: Session, product: Product, bin_: Bin) -> int:
    row = InventoryRepository(db).get_row(product.id, bin_.id)
    if row is None:
        return 0
    db.refresh(row)
    return row.quantity_on_hand


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ------------------------------------------------------------------------- policy
@pytest.mark.parametrize(
    ("kind", "needed"),
    [
        (AdjustmentKind.INCREASE, False),
        (AdjustmentKind.RESTORE, False),
        (AdjustmentKind.DECREASE, True),
        (AdjustmentKind.DAMAGE, True),
        (AdjustmentKind.WRITE_OFF, True),
    ],
)
def test_staff_need_approval_only_for_losses(users: dict, kind: AdjustmentKind, needed: bool):
    assert adjustment_needs_approval(kind, users["staff"]) is needed
    for approver in (users["manager"], users["admin"], None):  # None = the system
        assert adjustment_needs_approval(kind, approver) is False


# ---------------------------------------------------------------- adjustments
def test_staff_increase_is_applied_directly(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    result = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.INCREASE), user=users["staff"]
    )

    assert result.applied is True
    assert result.document.status == DocumentStatus.COMPLETED
    assert on_hand(db_session, product, bins["a"]) == 13


def test_staff_decrease_becomes_a_request_that_changes_nothing(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    movements = count(db_session, InventoryMovement)

    result = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE), user=users["staff"]
    )

    assert result.applied is False
    request = result.document
    assert (request.status, request.requested_by_id) == (DocumentStatus.PENDING, users["staff"].id)
    assert request.decided_by_id is None
    assert on_hand(db_session, product, bins["a"]) == 10
    # The dry run at creation left nothing behind: no movement, only the "request" audit.
    assert count(db_session, InventoryMovement) == movements
    actions = list(
        db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.entity_type.in_(["inventory", "stock_adjustment"])
            )
        )
    )
    assert actions == ["inventory.receive", "stock_adjustment.request"]


def test_impossible_requests_are_refused_immediately(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    with pytest.raises(InsufficientStockError, match="Only 10 units on hand"):
        service.submit_adjustment(
            adjustment(product, bins["a"], AdjustmentKind.DECREASE, 11), user=users["staff"]
        )

    assert count(db_session, StockAdjustment) == 0


def test_manager_approves_and_the_change_is_applied(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    request = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DAMAGE), user=users["staff"]
    ).document

    result = service.approve(request, approver=users["manager"], note="Checked the photos")

    row = result.inventory
    assert (row.quantity_on_hand, row.quantity_damaged) == (10, 3)
    assert request.status == DocumentStatus.COMPLETED
    assert (request.decided_by_id, request.decision_note) == (
        users["manager"].id,
        "Checked the photos",
    )
    assert request.decided_at is not None
    [movement] = result.movements
    assert (movement.reference_type, movement.reference_id) == ("adjustment", request.id)
    assert movement.created_by_id == users["manager"].id  # applied by the approver
    assert movement.reason == "Missing"  # the requester's reason is kept
    approved = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "stock_adjustment.approve")
    )
    assert approved.actor_id == users["manager"].id
    assert approved.summary == f"Adjustment request {request.id} approved: Checked the photos"


def test_approval_rechecks_todays_stock(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    request = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE, 8), user=users["staff"]
    ).document
    # Meanwhile a manager moves most of the stock away.
    service.submit_transfer(transfer(product, bins["a"], bins["b"], 5), user=users["manager"])

    with pytest.raises(InsufficientStockError, match="Only 5 units on hand"):
        service.approve(request, approver=users["manager"])

    db_session.refresh(request)
    assert request.status == DocumentStatus.PENDING  # still waiting; can be rejected
    assert on_hand(db_session, product, bins["a"]) == 5
    service.reject(request, approver=users["manager"], note="Stock was moved, count again")
    assert request.status == DocumentStatus.REJECTED


def test_rejecting_needs_a_note():
    with pytest.raises(ValidationError):
        RejectRequest(note="  ")
    assert RejectRequest(note="Units were found").note == "Units were found"


def test_write_off_request_without_damaged_units_is_refused(
    service: ApprovalService, product, bins, users, stocked
):
    with pytest.raises(InsufficientStockError, match="Only 0 damaged units"):
        service.submit_adjustment(
            adjustment(product, bins["a"], AdjustmentKind.WRITE_OFF), user=users["staff"]
        )


def test_reject(db_session: Session, service: ApprovalService, product, bins, users, stocked):
    request = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE), user=users["staff"]
    ).document

    service.reject(request, approver=users["admin"], note="Units were found")

    assert (request.status, request.decided_by_id) == (DocumentStatus.REJECTED, users["admin"].id)
    assert request.decision_note == "Units were found"
    assert on_hand(db_session, product, bins["a"]) == 10
    with pytest.raises(ConflictError, match="already rejected"):
        service.approve(request, approver=users["manager"])


def test_who_may_decide(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    request = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE), user=users["staff"]
    ).document

    with pytest.raises(PermissionDeniedError, match="Only managers and admins"):
        service.approve(request, approver=users["staff2"])
    with pytest.raises(PermissionDeniedError, match="Only managers and admins"):
        service.reject(request, approver=users["staff"], note="Nope")

    # A request can never be decided by the person who made it (four-eyes rule).
    own = StockAdjustment(
        product_id=product.id,
        bin_id=bins["a"].id,
        kind=AdjustmentKind.DECREASE,
        quantity=1,
        reason="Lost",
        requested_by_id=users["manager"].id,
    )
    db_session.add(own)
    db_session.commit()
    with pytest.raises(PermissionDeniedError, match="your own request"):
        service.approve(own, approver=users["manager"])


def test_cancel(db_session: Session, service: ApprovalService, product, bins, users, stocked):
    request = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE), user=users["staff"]
    ).document

    with pytest.raises(PermissionDeniedError, match="Only the person who made the request"):
        service.cancel(request, user=users["staff2"])
    service.cancel(request, user=users["staff"])

    assert request.status == DocumentStatus.CANCELLED
    with pytest.raises(ConflictError, match="already cancelled"):
        service.cancel(request, user=users["staff"])
    with pytest.raises(ConflictError):
        service.approve(request, approver=users["manager"])


# ------------------------------------------------------------------ transfers
def test_staff_transfer_within_a_warehouse_is_direct(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    result = service.submit_transfer(transfer(product, bins["a"], bins["b"]), user=users["staff"])

    assert result.applied is True
    assert on_hand(db_session, product, bins["b"]) == 4


def test_staff_transfer_to_another_warehouse_needs_approval(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    result = service.submit_transfer(
        transfer(product, bins["a"], bins["other_site"]), user=users["staff"]
    )
    assert result.applied is False
    assert result.document.status == DocumentStatus.PENDING
    assert on_hand(db_session, product, bins["other_site"]) == 0

    service.approve(result.document, approver=users["manager"])

    assert on_hand(db_session, product, bins["a"]) == 6
    assert on_hand(db_session, product, bins["other_site"]) == 4  # total still 10
    assert result.document.status == DocumentStatus.COMPLETED


def test_manager_transfer_to_another_warehouse_is_direct(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    result = service.submit_transfer(
        transfer(product, bins["a"], bins["other_site"]), user=users["manager"]
    )

    assert result.applied is True
    assert on_hand(db_session, product, bins["other_site"]) == 4


def test_impossible_transfer_requests_are_refused_immediately(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    with pytest.raises(InsufficientStockError, match="Only 10 units"):
        service.submit_transfer(
            transfer(product, bins["a"], bins["other_site"], 11), user=users["staff"]
        )
    assert count(db_session, StockTransfer) == 0


# --------------------------------------------------------------------- queue
def test_pending_queue_lists_open_requests_oldest_first(
    db_session: Session, service: ApprovalService, product, bins, users, stocked
):
    staff = users["staff"]
    first = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DECREASE, 1), user=staff
    ).document
    second = service.submit_transfer(
        transfer(product, bins["a"], bins["other_site"], 1), user=staff
    ).document
    decided = service.submit_adjustment(
        adjustment(product, bins["a"], AdjustmentKind.DAMAGE, 1), user=staff
    ).document
    service.reject(decided, approver=users["manager"], note="Not damaged")

    assert service.pending() == [first, second]
    assert service.get(StockTransfer, second.id) is second
    with pytest.raises(RequestNotFoundError):
        service.get(StockAdjustment, 99999)
