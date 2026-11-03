"""Reusable column mixins for ORM models."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.types import UTCDateTime


class IdMixin:
    """Integer auto-increment primary key."""

    id: Mapped[int] = mapped_column(primary_key=True)


class TimestampMixin:
    """`created_at` / `updated_at` columns maintained automatically (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
