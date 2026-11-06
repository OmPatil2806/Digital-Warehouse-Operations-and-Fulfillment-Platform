"""Cycle counts: physically count one bin and correct the system stock.

Life cycle:

    start  ->  OPEN  --record counts-->  OPEN  --submit-->  SUBMITTED
                 ^                                              |
                 +------------- reject (count again) -----------+
                                                                |
                                              approve --> COMPLETED (stock corrected)
    OPEN or SUBMITTED --cancel--> CANCELLED

- `start` stores what the system expects in the bin (on-hand of every product there).
- Counters enter what they really find; products that were not expected can be added.
- A manager or admin who did NOT start the count approves it (four-eyes rule).

On approval each line's variance (counted - expected) is applied to the CURRENT stock as a
`cycle_count` movement. Using the difference (not "set to counted") keeps every movement
that happened after the count started, e.g. a pick, correctly in the history. Capacity is
not checked: the counted units are physically there already. If a correction would leave
fewer units on hand than are reserved or damaged, approval is refused and the count stays
submitted, so it can be sent back for a recount.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, UnprocessableError
from app.models.inventory import (
    CycleCount,
    CycleCountLine,
    CycleCountStatus,
    MovementType,
    ReferenceType,
)
from app.models.user import User
from app.schemas.inventory import CycleCountRecord, CycleCountStart
from app.services.approval_service import APPROVER_ROLES
from app.services.audit_service import AuditService
from app.services.inventory_service import InventoryService

logger = get_logger(__name__)

UNFINISHED = (CycleCountStatus.OPEN.value, CycleCountStatus.SUBMITTED.value)


class CycleCountNotFoundError(NotFoundError):
    message = "Cycle count not found"


class CycleCountService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ read
    def get(self, count_id: int) -> CycleCount:
        count = self.db.scalar(
            select(CycleCount)
            .options(selectinload(CycleCount.lines))
            .where(CycleCount.id == count_id)
        )
        if count is None:
            raise CycleCountNotFoundError()
        return count

    # ----------------------------------------------------------------- start
    def start(self, data: CycleCountStart, *, user: User | None) -> CycleCount:
        bin_ = self.inventory.get_bin(data.bin_id, allow_archived=True)
        unfinished = self.unfinished_for_bin(bin_.id)
        if unfinished is not None:
            raise ConflictError(f"Bin {bin_.location_code} is already being counted ({unfinished})")
        count = self.open_count(bin_.id, note=data.note, user=user)
        self.db.commit()
        return count

    def unfinished_for_bin(self, bin_id: int) -> int | None:
        return self.db.scalar(
            select(CycleCount.id).where(
                CycleCount.bin_id == bin_id, CycleCount.status.in_(UNFINISHED)
            )
        )

    def open_count(self, bin_id: int, *, note: str | None, user: User | None) -> CycleCount:
        """Open a count for a bin without committing (e.g. after a short pick)."""
        bin_ = self.inventory.get_bin(bin_id, allow_archived=True)

        count = CycleCount(
            bin_id=bin_.id,
            status=CycleCountStatus.OPEN,
            note=note,
            requested_by_id=user.id if user else None,
        )
        count.lines = [
            CycleCountLine(product_id=row.product_id, expected_quantity=row.quantity_on_hand)
            for row in sorted(self.inventory.repo.rows_in_bin(bin_.id), key=lambda r: r.product_id)
        ]
        self.db.add(count)
        self.db.flush()
        self._audit(count, "start", user, f"Started counting {bin_.location_code}")
        return count

    # ---------------------------------------------------------------- record
    def record(self, count_id: int, data: CycleCountRecord, *, user: User | None) -> CycleCount:
        """Enter or correct counted quantities while the count is open."""
        count = self.get(count_id)
        self._require(count, CycleCountStatus.OPEN)
        lines = {line.product_id: line for line in count.lines}
        for entry in data.lines:
            line = lines.get(entry.product_id)
            if line is None:  # a product that was not expected in this bin
                product = self.inventory.get_product(entry.product_id, allow_archived=True)
                row = self.inventory.repo.get_row(product.id, count.bin_id)
                line = CycleCountLine(
                    product_id=product.id,
                    expected_quantity=row.quantity_on_hand if row else 0,
                )
                count.lines.append(line)
                lines[product.id] = line
            line.counted_quantity = entry.counted_quantity
        self.db.commit()
        return count

    # ---------------------------------------------------------------- submit
    def submit(self, count_id: int, *, user: User | None) -> CycleCount:
        count = self.get(count_id)
        self._require(count, CycleCountStatus.OPEN)
        missing = [line for line in count.lines if line.counted_quantity is None]
        if missing:
            raise UnprocessableError(f"{len(missing)} product(s) have not been counted yet")
        count.status = CycleCountStatus.SUBMITTED
        count.submitted_at = datetime.now(UTC)
        differences = sum(1 for line in count.lines if line.variance)
        self._audit(
            count, "submit", user, f"Count {count.id} submitted with {differences} difference(s)"
        )
        self.db.commit()
        return count

    # --------------------------------------------------------------- decide
    def approve(self, count_id: int, *, approver: User, note: str | None = None) -> CycleCount:
        """Apply every difference to the stock as cycle_count movements."""
        count = self.get(count_id)
        self._check_can_decide(count, approver)
        try:
            for line in count.lines:
                if not line.variance:
                    continue
                if line.variance > 0:
                    row = self.inventory.repo.get_or_create_row(line.product_id, count.bin_id)
                else:
                    row = self.inventory.repo.get_row(line.product_id, count.bin_id)
                    if row is None:  # cannot happen: expected > 0 means a row exists
                        raise ConflictError(f"No stock row for product {line.product_id}")
                self.inventory.change(
                    row,
                    MovementType.CYCLE_COUNT,
                    abs(line.variance),
                    on_hand=line.variance,
                    reference=(ReferenceType.CYCLE_COUNT, count.id),
                    reason=f"Cycle count {count.id}: expected {line.expected_quantity}, "
                    f"counted {line.counted_quantity}",
                    user=approver,
                )
            count.status = CycleCountStatus.COMPLETED
            self._decide(count, approver, note)
            corrections = [
                f"{line.product.sku} {line.variance:+d}" for line in count.lines if line.variance
            ]
            self._audit(
                count,
                "approve",
                approver,
                f"Count {count.id} approved: " + (", ".join(corrections) or "no differences"),
            )
        except Exception:
            self.db.rollback()  # nothing is corrected; the count stays submitted
            raise
        self.inventory.commit()
        logger.info("Cycle count %s approved by %s", count.id, approver.id)
        return count

    def reject(self, count_id: int, *, approver: User, note: str) -> CycleCount:
        """Send the count back for a recount (it becomes open again)."""
        count = self.get(count_id)
        self._check_can_decide(count, approver)
        count.status = CycleCountStatus.OPEN
        count.submitted_at = None
        self._decide(count, approver, note)
        self._audit(count, "reject", approver, f"Count {count.id} sent back for recount: {note}")
        self.db.commit()
        return count

    def cancel(self, count_id: int, *, user: User) -> CycleCount:
        """The person who started the count, or a manager/admin, can cancel it."""
        count = self.get(count_id)
        if count.status not in UNFINISHED:
            raise ConflictError(f"This count is already {count.status}")
        if count.requested_by_id != user.id and not user.has_role(*APPROVER_ROLES):
            raise PermissionDeniedError(
                "Only the person who started the count or a manager can cancel it"
            )
        count.status = CycleCountStatus.CANCELLED
        self._audit(count, "cancel", user, f"Count {count.id} cancelled")
        self.db.commit()
        return count

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _require(count: CycleCount, status: CycleCountStatus) -> None:
        if count.status != status:
            raise ConflictError(f"This count is {count.status}, not {status.value}")

    def _check_can_decide(self, count: CycleCount, approver: User) -> None:
        self._require(count, CycleCountStatus.SUBMITTED)
        if not approver.has_role(*APPROVER_ROLES):
            raise PermissionDeniedError("Only managers and admins can approve or reject counts")
        if count.requested_by_id == approver.id:
            raise PermissionDeniedError("You cannot approve or reject a count you started")

    @staticmethod
    def _decide(count: CycleCount, approver: User, note: str | None) -> None:
        count.decided_by = approver
        count.decided_at = datetime.now(UTC)
        count.decision_note = note

    def _audit(self, count: CycleCount, action: str, user: User | None, summary: str) -> None:
        self.audit.record(
            f"cycle_count.{action}",
            "cycle_count",
            count.id,
            summary=summary,
            changes={"status": {"new": count.status}},
            actor=user,
        )
