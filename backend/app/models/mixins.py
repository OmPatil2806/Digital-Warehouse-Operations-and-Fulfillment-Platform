"""Reusable column mixins for ORM models."""

from datetime import datetime
from enum import StrEnum

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


def one_of(column: str, values: type[StrEnum]) -> str:
    """SQL for `column IN ('a', 'b', ...)` built from an enum, for CHECK constraints.

    Building the list from the enum keeps the Python values and the database rule in sync.
    """
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"
