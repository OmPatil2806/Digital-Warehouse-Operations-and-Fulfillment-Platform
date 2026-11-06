"""Shipments: handing a packed order to a carrier (packed -> shipped).

The shipment takes the parcels and weight from the completed packing task, gets a
tracking number (given, or generated as <carrier code><yymmdd><order id>) and an expected
delivery date (given, or today + the carrier's transit days, counted in working days).
A "dispatched" event starts the tracking timeline. Every order line's packed units are
now shipped units.

Tracking after dispatch (`add_event`):

    in_transit / out_for_delivery   shipment in transit (a delayed one stays delayed)
    delayed                         shipment and order delayed; a delay_risk alert is raised
    delivered                       shipment and order delivered; the delay alert is resolved
    exception                       recorded only (e.g. address not found)

`mark_overdue` turns every shipment whose expected delivery date has passed into a
delayed one (run it daily, or call it from the API).
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit import AlertSeverity, AlertType
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
from app.schemas.fulfillment import ShipmentCreate, ShipmentEventCreate
from app.services.alert_service import AlertService, delay_key
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

    # ---------------------------------------------------------------- tracking
    def add_event(
        self, shipment_id: int, data: ShipmentEventCreate, *, user: User | None
    ) -> ShipmentEvent:
        shipment = self.get(shipment_id)
        if shipment.status == ShipmentStatus.DELIVERED:
            raise ConflictError(f"Shipment {shipment.tracking_number} is already delivered")
        now = datetime.now(UTC)
        occurred = data.occurred_at or now
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        if occurred > now + timedelta(minutes=5):
            raise UnprocessableError("A tracking event cannot be in the future")
        if occurred < shipment.shipped_at:
            raise UnprocessableError("A tracking event cannot be before the shipment was sent")
        event = self._record(shipment, ShipmentEventType(data.event_type), occurred, data, user)
        self.db.commit()
        return event

    def mark_overdue(self, *, today: date | None = None) -> list[Shipment]:
        """Delay every open shipment whose expected delivery date has passed."""
        today = today or datetime.now(UTC).date()
        late = self.db.scalars(
            select(Shipment).where(
                Shipment.status.in_(
                    [ShipmentStatus.DISPATCHED.value, ShipmentStatus.IN_TRANSIT.value]
                ),
                Shipment.expected_delivery_date < today,
            )
        ).all()
        now = datetime.now(UTC)
        for shipment in late:
            self._record(
                shipment,
                ShipmentEventType.DELAYED,
                now,
                ShipmentEventCreate(
                    event_type="delayed",
                    description=f"Not delivered by {shipment.expected_delivery_date.isoformat()}",
                ),
                None,
            )
        self.db.commit()
        if late:
            logger.info("Marked %s shipment(s) as delayed", len(late))
        return list(late)

    def _record(
        self,
        shipment: Shipment,
        event_type: ShipmentEventType,
        occurred: datetime,
        data: ShipmentEventCreate,
        user: User | None,
    ) -> ShipmentEvent:
        """Add the event and apply its effect on the shipment and the order (no commit)."""
        event = ShipmentEvent(
            event_type=event_type,
            occurred_at=occurred,
            location=data.location,
            description=data.description,
            created_by_id=user.id if user else None,
        )
        shipment.events.append(event)
        order = shipment.order
        alerts = AlertService(self.db)
        if event_type in (ShipmentEventType.IN_TRANSIT, ShipmentEventType.OUT_FOR_DELIVERY):
            if shipment.status == ShipmentStatus.DISPATCHED:
                shipment.status = ShipmentStatus.IN_TRANSIT
        elif event_type == ShipmentEventType.DELAYED:
            shipment.status = ShipmentStatus.DELAYED
            if order.status == OrderStatus.SHIPPED:
                self.orders.transition(order, OrderStatus.DELAYED, user=user, note=data.description)
            alerts.raise_alert(
                AlertType.DELAY_RISK,
                delay_key(order.id),
                severity=AlertSeverity.WARNING,
                title=f"Delayed: {order.order_number}",
                message=(
                    f"{shipment.carrier.code} {shipment.tracking_number}, expected "
                    f"{shipment.expected_delivery_date.isoformat()}"
                    + (f": {data.description}" if data.description else "")
                ),
                warehouse_id=order.warehouse_id,
            )
        elif event_type == ShipmentEventType.DELIVERED:
            shipment.status = ShipmentStatus.DELIVERED
            shipment.delivered_at = occurred
            self.orders.transition(
                order, OrderStatus.DELIVERED, user=user, note=data.location or None
            )
            order.delivered_at = occurred  # when it really happened, not when it was entered
            alerts.resolve_cause(delay_key(order.id))
        self.audit.record(
            f"shipment.{event_type.value}",
            "shipment",
            shipment.id,
            summary=f"{shipment.carrier.code} {shipment.tracking_number}: "
            f"{event_type.value.replace('_', ' ')}"
            + (f" ({data.location})" if data.location else ""),
            actor=user,
        )
        return event
