"""Custom column types."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware UTC datetime column.

    SQLite has no timezone support, so values are stored as UTC and every value read
    back is marked as UTC. This lets the code always compare with `datetime.now(UTC)`
    and makes the API return timestamps with an explicit `Z` / `+00:00`.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ScaledDecimal(TypeDecorator[Decimal]):
    """An exact decimal stored as an integer number of the smallest unit.

    SQLite has no real decimal type: SQLAlchemy's `Numeric` would store floating-point
    numbers, so 19.99 could come back as 19.989999... Instead, `ScaledDecimal(scale=2)`
    stores 19.99 as the integer 1999 and returns `Decimal("19.99")`. Values stay exact,
    and sorting, comparisons, SUM() and CHECK constraints still work in SQL.

    Values with more decimal places than `scale` are rejected (never silently rounded).
    """

    impl = Integer
    cache_ok = True

    def __init__(self, scale: int = 2) -> None:
        super().__init__()
        if scale < 0:
            raise ValueError("scale must be >= 0")
        self.scale = scale
        self._factor = Decimal(10) ** scale

    def process_bind_param(self, value: Decimal | int | str | None, dialect: Dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("ScaledDecimal does not accept float; use Decimal or str")
        scaled = Decimal(value) * self._factor
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{value} has more than {self.scale} decimal places")
        return int(scaled)

    def process_result_value(self, value: int | None, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return (Decimal(value) / self._factor).quantize(Decimal(1).scaleb(-self.scale))

    def coerce_compared_value(self, op: object, value: object) -> TypeDecorator[Decimal]:
        # Comparisons like `Product.unit_price > Decimal("10")` must scale the literal too.
        return self
