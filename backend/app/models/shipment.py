"""Carriers, shipments and their tracking events.

One shipment per order: the packed parcels handed to a carrier with a tracking number.
Every change of a shipment (dispatched, in transit, delayed, delivered, ...) is recorded
as a `shipment_events` row, which gives the customer a tracking timeline and gives the
delay-prediction model of Phase 8 its history.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Weight
from app.models.mixins import IdMixin, TimestampMixin, one_of
from app.models.order import Order
from app.models.user import User


class Carrier(IdMixin, TimestampMixin, Base):
    __tablename__ = "carriers"
    __table_args__ = (
        CheckConstraint("default_transit_days >= 0", name="transit_days_not_negative"),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # DHL
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # e.g. "https://track.example.com/{tracking_number}"
    tracking_url_template: Mapped[str | None] = mapped_column(String(255))
    default_transit_days: Mapped[int] = mapped_column(default=2, server_default="2")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    def tracking_url(self, tracking_number: str) -> str | None:
        if not self.tracking_url_template:
            return None
        return self.tracking_url_template.replace("{tracking_number}", tracking_number)

    def __repr__(self) -> str:
        return f"<Carrier {self.code}>"


class ShipmentStatus(StrEnum):
    DISPATCHED = "dispatched"  # handed to the carrier
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    RETURNED = "returned"  # sent back to the warehouse


class ShipmentEventType(StrEnum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELAYED = "delayed"
    DELIVERED = "delivered"
    EXCEPTION = "exception"  # e.g. address not found
    RETURNED = "returned"


class Shipment(IdMixin, TimestampMixin, Base):
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint(
            "carrier_id", "tracking_number", name="uq_shipments_carrier_id_tracking_number"
        ),
        CheckConstraint(one_of("status", ShipmentStatus), name="valid_status"),
        CheckConstraint("package_count >= 1", name="packages_positive"),
        CheckConstraint("weight_kg > 0", name="weight_positive"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    carrier_id: Mapped[int] = mapped_column(
        ForeignKey("carriers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    tracking_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ShipmentStatus.DISPATCHED, server_default="dispatched", index=True
    )
    package_count: Mapped[int] = mapped_column(nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Weight, nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expected_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    order: Mapped[Order] = relationship()
    carrier: Mapped[Carrier] = relationship()
    created_by: Mapped[User | None] = relationship()
    events: Mapped[list["ShipmentEvent"]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(ShipmentEvent.occurred_at, ShipmentEvent.id)",
    )

    @property
    def tracking_url(self) -> str | None:
        return self.carrier.tracking_url(self.tracking_number)

    def __repr__(self) -> str:
        return f"<Shipment {self.tracking_number} {self.status}>"


class ShipmentEvent(IdMixin, Base):
    """One step of a shipment's journey (the tracking timeline)."""

    __tablename__ = "shipment_events"
    __table_args__ = (CheckConstraint(one_of("event_type", ShipmentEventType), name="valid_type"),)

    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )

    shipment: Mapped[Shipment] = relationship(back_populates="events")
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<ShipmentEvent {self.event_type} {self.occurred_at:%Y-%m-%d %H:%M}>"
