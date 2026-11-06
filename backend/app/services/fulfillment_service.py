"""Picking and packing.

Picking: turning an order's reservations into a walking route, and confirming picks.

    allocate   inventory_reserved -> allocated   one picking task per reservation
    start      allocated -> picking              (first task started)
    complete   ... -> picked                     (when no task of the order is open)

The route: farthest racks from the packing station first, so the picker ends at packing;
within a rack lower shelves first, then bin code. Completing a task needs the picker to
"scan" the bin's location code and the product's SKU or barcode; a wrong scan is
refused, which prevents picking errors.

Short pick (fewer units in the bin than the system expected):
- the picked units leave the bin, the rest of the reservation is released,
- the missing units are written off at once with the picker's reason (otherwise other
  orders could reserve units that are not there), and a cycle count is opened for the
  bin so a second person checks it (four-eyes),
- the missing units are reserved from another bin if possible (a new task is added to
  the route); otherwise the line ships short, which the order history records.

Packing (picked -> packing -> packed): when the last pick is confirmed a packing task is
created; the packer counts each line into the parcels (must equal what was picked) and
records the number of parcels and the total weight, which the shipment then uses.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.fulfillment import (
    OPEN_PICKING_STATUSES,
    PackingTask,
    PackingTaskStatus,
    PickingTask,
    PickingTaskStatus,
)
from app.models.inventory import (
    AdjustmentKind,
    DocumentStatus,
    ReferenceType,
    ReservationStatus,
    StockAdjustment,
    StockReservation,
)
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.models.warehouse import Bin, Rack, Shelf
from app.schemas.fulfillment import PackConfirmation, PickConfirmation
from app.services.audit_service import AuditService
from app.services.cycle_count_service import CycleCountService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderService

logger = get_logger(__name__)

S = OrderStatus
T = PickingTaskStatus
P = PackingTaskStatus


class PickingTaskNotFoundError(NotFoundError):
    message = "Picking task not found"


class PackingTaskNotFoundError(NotFoundError):
    message = "Packing task not found"


def route_key(bin_: Bin) -> tuple:
    """Sort key for the picking route: farthest from packing first, then shelf, then bin."""
    rack = bin_.shelf.rack
    return (-rack.distance_to_packing_m, rack.zone.code, rack.code, bin_.shelf.level, bin_.code)


class FulfillmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.inventory = InventoryService(db)
        self.orders = OrderService(db)
        self.audit = AuditService(db)

    # ------------------------------------------------------------------- read
    def get_task(self, task_id: int) -> PickingTask:
        task = self.db.get(PickingTask, task_id)
        if task is None:
            raise PickingTaskNotFoundError()
        return task

    def tasks_for_order(self, order_id: int) -> Sequence[PickingTask]:
        return self.db.scalars(
            select(PickingTask)
            .where(PickingTask.order_id == order_id)
            .order_by(PickingTask.sequence)
        ).all()

    # ---------------------------------------------------------------- allocate
    def allocate(self, order_id: int, *, user: User | None) -> list[PickingTask]:
        """Create the picking route for a fully reserved order (-> allocated)."""
        order = self.orders.get(order_id)
        self.orders.transition(order, S.ALLOCATED, user=user)
        tasks = self._tasks_for_reservations(order, self._active_reservations(order), start=1)
        if not tasks:
            raise ConflictError(f"Order {order.order_number} has no reserved stock to pick")
        order.history[-1].note = f"{len(tasks)} picking task(s) created"
        self.db.commit()
        logger.info("Allocated %s: %s picking tasks", order.order_number, len(tasks))
        return tasks

    # ------------------------------------------------------------------- start
    def start(self, task_id: int, *, user: User) -> PickingTask:
        task = self.get_task(task_id)
        if task.status != T.PENDING:
            raise ConflictError(f"Picking task {task.id} is already {_label(task.status)}")
        order = task.order
        if order.status not in (S.ALLOCATED, S.PICKING):
            raise ConflictError(
                f"Order {order.order_number} is {_label(order.status)}; it cannot be picked now"
            )
        task.status = T.IN_PROGRESS
        task.assigned_to = user
        task.started_at = datetime.now(UTC)
        if order.status == S.ALLOCATED:
            self.orders.transition(order, S.PICKING, user=user, note=f"Picked by {user.full_name}")
        self.db.commit()
        return task

    # ---------------------------------------------------------------- complete
    def complete(self, task_id: int, data: PickConfirmation, *, user: User) -> PickingTask:
        """Confirm a pick with scans; handles short picks (see module docstring)."""
        task = self.get_task(task_id)
        if task.status != T.IN_PROGRESS:
            raise ConflictError(
                f"Picking task {task.id} is {_label(task.status)}; start it before confirming"
            )
        self._check_scans(task, data)
        picked = data.quantity_picked
        short = task.quantity - picked
        if short and not data.short_reason:
            raise UnprocessableError(
                f"Only {picked} of {task.quantity} picked: say why units are missing"
            )
        order = task.order
        try:
            self.inventory.consume_reservation(
                task.reservation,
                picked,
                reference=(ReferenceType.ORDER, order.id),
                reason=f"Order {order.order_number}",
                user=user,
            )
            item = task.order_item
            item.quantity_reserved -= task.quantity
            item.quantity_picked += picked
            task.quantity_picked = picked
            task.completed_at = datetime.now(UTC)
            task.status = T.SHORT if short else T.COMPLETED
            if short:
                task.short_reason = data.short_reason
                self._handle_short_pick(task, short, user=user)
            self._finish_order_if_done(order, user=user)
        except Exception:
            self.db.rollback()
            raise
        self.inventory.commit()
        return task

    # ------------------------------------------------------------- cancellation
    def cancel_open_tasks(self, order: Order) -> int:
        """Called when an allocated order is cancelled (no commit)."""
        count = 0
        for task in self.tasks_for_order(order.id):
            if task.status in OPEN_PICKING_STATUSES:
                task.status = T.CANCELLED
                count += 1
        return count

    # ---------------------------------------------------------------- helpers
    def _active_reservations(self, order: Order) -> list[StockReservation]:
        return list(
            self.db.scalars(
                select(StockReservation)
                .options(
                    joinedload(StockReservation.bin)
                    .joinedload(Bin.shelf)
                    .joinedload(Shelf.rack)
                    .joinedload(Rack.zone)
                )
                .where(
                    StockReservation.reference_type == ReferenceType.ORDER.value,
                    StockReservation.reference_id == order.id,
                    StockReservation.status == ReservationStatus.ACTIVE.value,
                    StockReservation.id.not_in(select(PickingTask.reservation_id)),
                )
            )
        )

    def _tasks_for_reservations(
        self, order: Order, reservations: list[StockReservation], *, start: int
    ) -> list[PickingTask]:
        items = {item.product_id: item for item in order.items}
        tasks = []
        for sequence, reservation in enumerate(
            sorted(reservations, key=lambda r: route_key(r.bin)), start=start
        ):
            task = PickingTask(
                order_id=order.id,
                order_item_id=items[reservation.product_id].id,
                reservation_id=reservation.id,
                product_id=reservation.product_id,
                bin_id=reservation.bin_id,
                quantity=reservation.quantity,
                sequence=sequence,
                status=T.PENDING,
            )
            self.db.add(task)
            tasks.append(task)
        self.db.flush()
        return tasks

    @staticmethod
    def _check_scans(task: PickingTask, data: PickConfirmation) -> None:
        scanned_bin = data.bin_code.strip().upper()
        if scanned_bin != task.bin.location_code:
            raise UnprocessableError(
                f"Wrong bin: scanned {scanned_bin}, the task is for {task.bin.location_code}"
            )
        scanned = data.product_code.strip().upper()
        product = task.product
        if scanned not in {product.sku, (product.barcode or "").upper()}:
            raise UnprocessableError(
                f"Wrong product: scanned {scanned}, the task is for {product.sku}"
            )

    def _handle_short_pick(self, task: PickingTask, short: int, *, user: User) -> None:
        order = task.order
        reason = f"Short pick on order {order.order_number}: {task.short_reason}"
        # 1. The missing units are not in the bin: take them out of the system stock. (At
        #    most what other orders have not reserved; the cycle count sorts out the rest.)
        row = self.inventory.repo.get_row(task.product_id, task.bin_id)
        write_off = min(short, row.quantity_available if row else 0)
        if write_off:
            self._write_off(task, write_off, reason=reason, user=user)
        # 2. A second person checks the bin.
        counts = CycleCountService(self.db)
        if counts.unfinished_for_bin(task.bin_id) is None:
            counts.open_count(task.bin_id, note=reason[:255], user=user)
        # 3. Try another bin of the same warehouse for the missing units.
        item = task.order_item
        result = self.inventory.reserve_available(
            task.product,
            short,
            reference=(ReferenceType.ORDER, order.id),
            warehouse_id=order.warehouse_id,
            user=user,
            reason=f"Order {order.order_number} (replaces short pick)",
        )
        item.quantity_reserved += result.quantity
        last = max(t.sequence for t in self.tasks_for_order(order.id))
        self._tasks_for_reservations(order, result.reservations, start=last + 1)
        note = f"Short pick of {short} x {task.product.sku} in {task.bin.location_code}"
        if result.quantity < short:
            note += f"; {short - result.quantity} unit(s) not available, the line ships short"
        self.audit.record("order.short_pick", "order", order.id, summary=note, actor=user)

    def _write_off(self, task: PickingTask, quantity: int, *, reason: str, user: User) -> None:
        """Remove units the picker did not find (a completed DECREASE adjustment)."""
        adjustment = StockAdjustment(
            product_id=task.product_id,
            bin_id=task.bin_id,
            kind=AdjustmentKind.DECREASE,
            quantity=quantity,
            reason=reason[:255],
            status=DocumentStatus.COMPLETED,
            requested_by_id=user.id,
            decided_by_id=user.id,
            decided_at=datetime.now(UTC),
        )
        self.db.add(adjustment)
        self.db.flush()
        self.inventory.apply_adjustment(adjustment, product=task.product, bin_=task.bin, user=user)

    def _finish_order_if_done(self, order: Order, *, user: User) -> None:
        open_tasks = [
            t for t in self.tasks_for_order(order.id) if t.status in OPEN_PICKING_STATUSES
        ]
        if open_tasks:
            return
        missing = sum(i.quantity - i.quantity_picked for i in order.items)
        note = "All units picked" if not missing else f"Picked with {missing} unit(s) short"
        self.orders.transition(order, S.PICKED, user=user, note=note)
        if any(item.quantity_picked for item in order.items):
            self.db.add(PackingTask(order_id=order.id, status=P.PENDING))  # to the packing station

    # ================================================================ packing
    def get_packing_task(self, task_id: int) -> PackingTask:
        task = self.db.get(PackingTask, task_id)
        if task is None:
            raise PackingTaskNotFoundError()
        return task

    def packing_task_for_order(self, order_id: int) -> PackingTask | None:
        return self.db.scalar(select(PackingTask).where(PackingTask.order_id == order_id))

    def start_packing(self, task_id: int, *, user: User) -> PackingTask:
        task = self.get_packing_task(task_id)
        if task.status != P.PENDING:
            raise ConflictError(f"Packing task {task.id} is already {_label(task.status)}")
        task.status = P.IN_PROGRESS
        task.packed_by = user
        task.started_at = datetime.now(UTC)
        self.orders.transition(task.order, S.PACKING, user=user, note=f"Packed by {user.full_name}")
        self.db.commit()
        return task

    def complete_packing(self, task_id: int, data: PackConfirmation, *, user: User) -> PackingTask:
        """The packer confirms every picked line went into the parcels (-> packed)."""
        task = self.get_packing_task(task_id)
        if task.status != P.IN_PROGRESS:
            raise ConflictError(
                f"Packing task {task.id} is {_label(task.status)}; start it before confirming"
            )
        order = task.order
        counted = {line.product_id: line.quantity for line in data.items}
        problems = []
        for item in order.items:
            if item.quantity_picked == 0:
                continue  # nothing was picked for this line (shipped short)
            packed = counted.pop(item.product_id, 0)
            if packed != item.quantity_picked:
                problems.append(
                    f"{item.product.sku}: {packed} packed, {item.quantity_picked} picked"
                )
        problems += [f"product {pid} is not part of this order" for pid in counted]
        if problems:
            raise UnprocessableError(
                "Packed items do not match the picked items: " + "; ".join(problems)
            )
        for item in order.items:
            item.quantity_packed = item.quantity_picked
        task.status = P.COMPLETED
        task.completed_at = datetime.now(UTC)
        task.package_count = data.package_count
        task.weight_kg = data.weight_kg
        task.note = data.note
        self.orders.transition(
            order,
            S.PACKED,
            user=user,
            note=f"{data.package_count} parcel(s), {data.weight_kg} kg",
        )
        self.db.commit()
        return task


def _label(status: str) -> str:
    return status.replace("_", " ")
