"""Audit log (who changed what, when, old and new values) and alerts.

Audit rows are append-only: the database refuses UPDATE and DELETE on `audit_logs`
(triggers created by the migration). The actor is stored as id *and* e-mail without a
foreign key, so the history stays readable even if a user record were ever removed.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.catalog import Product
from app.models.mixins import IdMixin, TimestampMixin, one_of
from app.models.user import User
from app.models.warehouse import Bin, Warehouse


class AuditAction(StrEnum):
    """Generic actions written automatically for tracked models.

    Business operations use dotted names instead, e.g. "inventory.receive".
    """

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_id_created_at", "actor_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), index=True, nullable=False
    )
    # NULL = the system (seed script, create_admin, background jobs).
    actor_id: Mapped[int | None] = mapped_column()
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int | None] = mapped_column()
    summary: Mapped[str | None] = mapped_column(String(255))
    # {"field": {"old": ..., "new": ...}}; "create" has only "new", "delete" only "old".
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}:{self.entity_id}>"


class AlertType(StrEnum):
    LOW_STOCK = "low_stock"  # available stock below the product's min_stock (Phase 4)
    OVER_CAPACITY = "over_capacity"  # bin weight/volume above its limits (Phase 4)
    PREDICTED_STOCKOUT = "predicted_stockout"  # ML (Phase 8/9)
    DELAY_RISK = "delay_risk"  # ML (Phase 8/9)
    OVERDUE_SUPPLIER = "overdue_supplier"  # purchase orders (Phase 5)


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(StrEnum):
    OPEN = "open"  # new, nobody has looked at it
    ACKNOWLEDGED = "acknowledged"  # someone is on it
    RESOLVED = "resolved"  # the cause is gone (often closed automatically)


class Alert(IdMixin, TimestampMixin, Base):
    """A problem that needs attention, e.g. "LAP-001 is below its minimum stock"."""

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(one_of("alert_type", AlertType), name="valid_alert_type"),
        CheckConstraint(one_of("severity", AlertSeverity), name="valid_severity"),
        CheckConstraint(one_of("status", AlertStatus), name="valid_status"),
        # At most one unresolved alert per cause, e.g. "low_stock:product:7". A new alert
        # for the same cause can only be raised after the previous one was resolved.
        Index(
            "uq_alerts_unresolved_dedup_key",
            "dedup_key",
            unique=True,
            sqlite_where=text("status != 'resolved'"),
        ),
    )

    alert_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=AlertStatus.OPEN, server_default="open", index=True
    )
    dedup_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    # What the alert is about (all optional; depends on the alert type).
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("bins.id", ondelete="CASCADE"))
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE")
    )
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # NULL resolved_by_id with a resolved_at = closed automatically by the system.
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    product: Mapped[Product | None] = relationship()
    bin: Mapped[Bin | None] = relationship()
    warehouse: Mapped[Warehouse | None] = relationship()
    acknowledged_by: Mapped[User | None] = relationship(foreign_keys=[acknowledged_by_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} {self.status} {self.dedup_key}>"
