"""Manager approval of stock transfers and adjustments ("four-eyes" rule).

Who needs approval (project document: managers "approve transfers and adjustments"):

| Operation                                  | Staff            | Manager / admin |
|--------------------------------------------|------------------|-----------------|
| Transfer within one warehouse              | applied directly | applied directly|
| Transfer to another warehouse              | request          | applied directly|
| Adjustment: increase (found), restore      | applied directly | applied directly|
| Adjustment: decrease, damage, write-off    | request          | applied directly|

Operations that *lose* sellable stock, or move it between sites, need a second person.

A request is stored as a `pending` document. It does not hold any stock: when a manager
approves it, every rule (enough available stock, bin capacity, archived bins) is checked
again against the stock as it is *then*, and the change is applied exactly like a direct
operation (movement + audit record). If the stock no longer allows it, approval fails
with a clear message and the request stays pending, so the manager can reject it.

Requests are also checked when they are created (a dry run inside a savepoint that is
always rolled back), so staff get immediate feedback instead of a request that can
never be approved.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models.inventory import AdjustmentKind, DocumentStatus, StockAdjustment, StockTransfer
from app.models.user import RoleName, User
from app.models.warehouse import Bin
from app.schemas.inventory import AdjustmentRequest, TransferRequest
from app.services.audit_service import AuditService
from app.services.inventory_service import (
    InventoryService,
    StockOperationResult,
    TransferResult,
)

logger = get_logger(__name__)

APPROVER_ROLES = (RoleName.ADMIN, RoleName.MANAGER)
# Adjustment kinds that remove sellable stock.
LOSS_KINDS = {AdjustmentKind.DECREASE, AdjustmentKind.DAMAGE, AdjustmentKind.WRITE_OFF}

Document = StockAdjustment | StockTransfer


class RequestNotFoundError(NotFoundError):
    message = "Request not found"


@dataclass
class SubmitResult:
    """`applied` = the change was made now; otherwise `document` waits for approval."""

    document: Document
    applied: bool
    result: StockOperationResult | TransferResult | None = None


def is_approver(user: User | None) -> bool:
    """Managers and admins (and the system itself) never need a second person."""
    return user is None or user.has_role(*APPROVER_ROLES)


def warehouse_of(bin_: Bin) -> int:
    return bin_.shelf.rack.zone.warehouse_id


def adjustment_needs_approval(kind: AdjustmentKind, user: User | None) -> bool:
    return not is_approver(user) and AdjustmentKind(kind) in LOSS_KINDS


def transfer_needs_approval(from_bin: Bin, to_bin: Bin, user: User | None) -> bool:
    return not is_approver(user) and warehouse_of(from_bin) != warehouse_of(to_bin)


class ApprovalService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ submit
    def submit_adjustment(self, data: AdjustmentRequest, *, user: User | None) -> SubmitResult:
        """Apply the adjustment now, or store it as a request if it needs approval."""
        if not adjustment_needs_approval(data.kind, user):
            result = self.inventory.adjust(data, user=user)
            return SubmitResult(document=result.adjustment, applied=True, result=result)

        product = self.inventory.get_product(data.product_id, allow_archived=True)
        bin_ = self.inventory.get_bin(data.bin_id, allow_archived=True)
        request = StockAdjustment(
            product_id=product.id,
            bin_id=bin_.id,
            kind=data.kind,
            quantity=data.quantity,
            reason=data.reason,
            status=DocumentStatus.PENDING,
            requested_by_id=user.id if user else None,
        )
        self._store_request(
            request,
            check=lambda: self.inventory.apply_adjustment(
                request, product=product, bin_=bin_, user=user
            ),
            summary=(
                f"Requested {AdjustmentKind(data.kind).value.replace('_', ' ')}: "
                f"{data.quantity} x {product.sku} in {bin_.location_code} ({data.reason})"
            ),
            user=user,
        )
        return SubmitResult(document=request, applied=False)

    def submit_transfer(self, data: TransferRequest, *, user: User | None) -> SubmitResult:
        """Apply the transfer now, or store it as a request if it needs approval."""
        from_bin = self.inventory.get_bin(data.from_bin_id, allow_archived=True)
        to_bin = self.inventory.get_bin(data.to_bin_id)
        if not transfer_needs_approval(from_bin, to_bin, user):
            result = self.inventory.transfer(data, user=user)
            return SubmitResult(document=result.transfer, applied=True, result=result)

        product = self.inventory.get_product(data.product_id, allow_archived=True)
        request = StockTransfer(
            product_id=product.id,
            from_bin_id=from_bin.id,
            to_bin_id=to_bin.id,
            quantity=data.quantity,
            reason=data.reason,
            status=DocumentStatus.PENDING,
            requested_by_id=user.id if user else None,
        )
        self._store_request(
            request,
            check=lambda: self.inventory.apply_transfer(request, user=user),
            summary=(
                f"Requested transfer of {data.quantity} x {product.sku} from "
                f"{from_bin.location_code} to {to_bin.location_code} (another warehouse)"
            ),
            user=user,
        )
        return SubmitResult(document=request, applied=False)

    # ----------------------------------------------------------------- decide
    def approve(
        self, document: Document, *, approver: User, note: str | None = None
    ) -> StockOperationResult | TransferResult:
        """Apply a pending request. Every rule is checked again against today's stock."""
        self._check_can_decide(document, approver)
        try:
            if isinstance(document, StockAdjustment):
                result: StockOperationResult | TransferResult = self.inventory.apply_adjustment(
                    document,
                    product=self.inventory.get_product(document.product_id, allow_archived=True),
                    bin_=self.inventory.get_bin(document.bin_id, allow_archived=True),
                    user=approver,
                )
            else:
                result = self.inventory.apply_transfer(document, user=approver)
            self._decide(document, DocumentStatus.COMPLETED, approver, note)
        except Exception:
            self.db.rollback()  # the request stays pending
            raise
        self.inventory.commit()
        logger.info("%s %s approved by %s", _kind(document), document.id, approver.id)
        return result

    def reject(self, document: Document, *, approver: User, note: str) -> Document:
        self._check_can_decide(document, approver)
        self._decide(document, DocumentStatus.REJECTED, approver, note)
        self.db.commit()
        return document

    def cancel(self, document: Document, *, user: User) -> Document:
        """The requester withdraws their own pending request."""
        self._check_pending(document)
        if document.requested_by_id != user.id:
            raise PermissionDeniedError("Only the person who made the request can cancel it")
        document.status = DocumentStatus.CANCELLED
        document.decided_at = datetime.now(UTC)
        self._audit(document, "cancel", user, f"{_kind(document)} request {document.id} cancelled")
        self.db.commit()
        return document

    # ------------------------------------------------------------------ read
    def get(self, model: type[Document], document_id: int) -> Document:
        document = self.db.get(model, document_id)
        if document is None:
            raise RequestNotFoundError()
        return document

    def pending(self) -> list[Document]:
        """The approval queue: every pending request, oldest first."""
        documents: list[Document] = [
            *self.db.scalars(
                select(StockAdjustment).where(StockAdjustment.status == DocumentStatus.PENDING)
            ),
            *self.db.scalars(
                select(StockTransfer).where(StockTransfer.status == DocumentStatus.PENDING)
            ),
        ]
        return sorted(documents, key=lambda d: (d.created_at, d.id))

    # --------------------------------------------------------------- helpers
    def _store_request(
        self, request: Document, *, check: Callable[[], object], summary: str, user: User | None
    ) -> None:
        self.db.add(request)
        try:
            self.db.flush()  # the request id is needed by the dry run's movements
            savepoint = self.db.begin_nested()
            try:
                check()  # raises if the request could not be approved right now
            finally:
                savepoint.rollback()  # a dry run never changes anything
            self._audit(request, "request", user, summary)
        except Exception:
            self.db.rollback()
            raise
        self.db.commit()
        logger.info("%s request %s created by %s", _kind(request), request.id, user)

    def _check_pending(self, document: Document) -> None:
        if document.status != DocumentStatus.PENDING:
            raise ConflictError(f"This request is already {document.status}")

    def _check_can_decide(self, document: Document, approver: User) -> None:
        self._check_pending(document)
        if not approver.has_role(*APPROVER_ROLES):
            raise PermissionDeniedError("Only managers and admins can approve or reject requests")
        if document.requested_by_id == approver.id:
            raise PermissionDeniedError("You cannot approve or reject your own request")

    def _decide(
        self, document: Document, status: DocumentStatus, approver: User, note: str | None
    ) -> None:
        document.status = status
        document.decided_by = approver
        document.decided_at = datetime.now(UTC)
        document.decision_note = note
        verb = "approved" if status == DocumentStatus.COMPLETED else "rejected"
        self._audit(
            document,
            "approve" if status == DocumentStatus.COMPLETED else "reject",
            approver,
            f"{_kind(document)} request {document.id} {verb}" + (f": {note}" if note else ""),
        )

    def _audit(self, document: Document, action: str, user: User | None, summary: str) -> None:
        entity = "stock_adjustment" if isinstance(document, StockAdjustment) else "stock_transfer"
        self.audit.record(
            f"{entity}.{action}",
            entity,
            document.id,
            summary=summary,
            changes={"status": {"new": document.status}},
            actor=user,
        )


def _kind(document: Document) -> str:
    return "Adjustment" if isinstance(document, StockAdjustment) else "Transfer"
