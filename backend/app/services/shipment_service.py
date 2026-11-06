"""Shipments: handing a packed order to a carrier (packed -> shipped).

The shipment takes the parcels and weight from the completed packing task, gets a
tracking number (given, or generated as <carrier code><yymmdd><order id>) and an expected
delivery date (given, or today + the carrier's transit days, counted in working days).
A "dispatched" event starts the tracking timeline. Every order line's packed units are
now shipped units.

Tracking events after dispatch (in transit, delayed, delivered) come in the next step.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.fulfillment import PackingTask, PackingTaskStatus
from app.models.order import OrderStatus
from app.models.shipment import (
    Carrier,
    Shipment,
    ShipmentEvent,
    ShipmentEventType,
    ShipmentStatus,
)
from app.models.user import User
from app.schemas.fulfillment import ShipmentCreate
from app.services.audit_service import AuditService
from app.services.order_service import OrderService

logger = get_logger(__name__)


class ShipmentNotFoundError(NotFoundError):
    message = "Shipment not found"


def add_working_days(start: date, days: int) -> date:
    """start + `days` working days (Saturday and Sunday are skipped)."""
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


class ShipmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.orders = OrderService(db)
        self.audit = AuditService(db)

    def get(self, shipment_id: int) -> Shipment:
        shipment = self.db.get(Shipment, shipment_id)
        if shipment is None:
            raise ShipmentNotFoundError()
        return shipment

    def for_order(self, order_id: int) -> Shipment | None:
        return self.db.scalar(select(Shipment).where(Shipment.order_id == order_id))

    def create(self, order_id: int, data: ShipmentCreate, *, user: User | None) -> Shipment:
        order = self.orders.get(order_id)
        if order.status != OrderStatus.PACKED:
            raise ConflictError(
                f"Order {order.order_number} is {order.status.replace('_', ' ')}; only packed "
                "orders can be shipped"
            )
        packing = self.db.scalar(select(PackingTask).where(PackingTask.order_id == order.id))
        if packing is None or packing.status != PackingTaskStatus.COMPLETED:
            raise ConflictError(f"Order {order.order_number} has no completed packing")
        carrier = self.db.get(Carrier, data.carrier_id)
        if carrier is None:
            raise UnprocessableError("Carrier not found")
        if not carrier.is_active:
            raise UnprocessableError(f"Carrier {carrier.code} is not active")

        now = datetime.now(UTC)
        expected = data.expected_delivery_date or add_working_days(
            now.date(), carrier.default_transit_days
        )
        if expected < now.date():
            raise UnprocessableError("The expected delivery date cannot be in the past")
        tracking = (data.tracking_number or f"{carrier.code}{now:%y%m%d}{order.id:06d}").upper()
        shipment = Shipment(
            order_id=order.id,
            carrier_id=carrier.id,
            tracking_number=tracking,
            status=ShipmentStatus.DISPATCHED,
            package_count=packing.package_count,
            weight_kg=packing.weight_kg,
            shipped_at=now,
            expected_delivery_date=expected,
            created_by_id=user.id if user else None,
        )
        shipment.events = [
            ShipmentEvent(
                event_type=ShipmentEventType.DISPATCHED,
                occurred_at=now,
                location=order.warehouse.name if order.warehouse else None,
                description=f"Handed to {carrier.name}",
                created_by_id=user.id if user else None,
            )
        ]
        self.db.add(shipment)
        for item in order.items:
            item.quantity_shipped = item.quantity_packed
        self.orders.transition(
            order,
            OrderStatus.SHIPPED,
            user=user,
            note=f"{carrier.code} {tracking}, expected {expected.isoformat()}",
        )
        try:
            self.db.flush()
        except IntegrityError as exc:  # same tracking number for this carrier
            self.db.rollback()
            raise ConflictError(
                f"Tracking number {tracking} is already used for {carrier.code}"
            ) from exc
        self.audit.record(
            "shipment.create",
            "shipment",
            shipment.id,
            summary=(
                f"Order {order.order_number} shipped with {carrier.code} {tracking} "
                f"({shipment.package_count} parcel(s), {shipment.weight_kg} kg)"
            ),
            actor=user,
        )
        self.db.commit()
        logger.info("Shipped %s as %s %s", order.order_number, carrier.code, tracking)
        return shipment
