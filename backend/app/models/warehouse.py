"""Physical warehouse hierarchy: Warehouse > Zone > Rack > Shelf > Bin.

Every bin has a unique location code built from the codes of its parents:

    WH01 - ZA - R05 - S03 - B08
     |     |    |     |     +-- bin
     |     |    |     +-------- shelf (level)
     |     |    +-------------- rack
     |     +------------------- zone
     +------------------------- warehouse

Codes are unique within their parent; location codes are unique across the system.
Records that have children cannot be deleted (RESTRICT): archive them instead.
"""

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import ScaledDecimal
from app.models.mixins import IdMixin, TimestampMixin

LOCATION_CODE_SEPARATOR = "-"


class ZoneType(StrEnum):
    """What a zone is used for (drives slotting and put-away rules later)."""

    PICKING = "picking"  # fast access for order picking
    BULK = "bulk"  # reserve stock, pallets
    COLD = "cold"  # temperature-controlled goods
    HAZARDOUS = "hazardous"  # dangerous goods
    RETURNS = "returns"  # returned goods awaiting inspection


def build_location_code(
    warehouse_code: str, zone_code: str, rack_code: str, shelf_code: str, bin_code: str
) -> str:
    """e.g. ('WH01', 'ZA', 'R05', 'S03', 'B08') -> 'WH01-ZA-R05-S03-B08'."""
    return LOCATION_CODE_SEPARATOR.join(
        (warehouse_code, zone_code, rack_code, shelf_code, bin_code)
    )


class Warehouse(IdMixin, TimestampMixin, Base):
    __tablename__ = "warehouses"

    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # WH01
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    zones: Mapped[list["Zone"]] = relationship(back_populates="warehouse", order_by="Zone.code")

    def __repr__(self) -> str:
        return f"<Warehouse {self.code}>"


class Zone(IdMixin, TimestampMixin, Base):
    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code"),
        CheckConstraint(
            "zone_type IN ('picking', 'bulk', 'cold', 'hazardous', 'returns')",
            name="valid_zone_type",
        ),
    )

    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # ZA
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    warehouse: Mapped[Warehouse] = relationship(back_populates="zones")
    racks: Mapped[list["Rack"]] = relationship(back_populates="zone", order_by="Rack.code")

    def __repr__(self) -> str:
        return f"<Zone {self.code} ({self.zone_type})>"


class Rack(IdMixin, TimestampMixin, Base):
    __tablename__ = "racks"
    __table_args__ = (
        UniqueConstraint("zone_id", "code"),
        CheckConstraint("distance_to_packing_m >= 0", name="distance_not_negative"),
    )

    zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # R05
    # Walking distance from this rack to the packing station; used by slotting (Phase 8).
    distance_to_packing_m: Mapped[Decimal] = mapped_column(
        ScaledDecimal(scale=1), default=Decimal("0.0"), server_default="0", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="racks")
    shelves: Mapped[list["Shelf"]] = relationship(back_populates="rack", order_by="Shelf.level")

    def __repr__(self) -> str:
        return f"<Rack {self.code}>"


class Shelf(IdMixin, TimestampMixin, Base):
    __tablename__ = "shelves"
    __table_args__ = (
        UniqueConstraint("rack_id", "code"),
        UniqueConstraint("rack_id", "level"),
        CheckConstraint("level >= 1", name="level_positive"),
    )

    rack_id: Mapped[int] = mapped_column(
        ForeignKey("racks.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # S03
    # 1 = floor level. Heavy items belong on low levels (used by put-away rules).
    level: Mapped[int] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    rack: Mapped[Rack] = relationship(back_populates="shelves")
    bins: Mapped[list["Bin"]] = relationship(back_populates="shelf", order_by="Bin.code")

    def __repr__(self) -> str:
        return f"<Shelf {self.code} level={self.level}>"


class Bin(IdMixin, TimestampMixin, Base):
    """The smallest storage location. Stock (Phase 4) is always held in a bin."""

    __tablename__ = "bins"
    __table_args__ = (
        UniqueConstraint("shelf_id", "code"),
        CheckConstraint("max_weight_kg > 0", name="max_weight_positive"),
        CheckConstraint("max_volume_cm3 > 0", name="max_volume_positive"),
    )

    shelf_id: Mapped[int] = mapped_column(
        ForeignKey("shelves.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)  # B08
    # Full code, e.g. WH01-ZA-R05-S03-B08. Stored (not computed) so it can be searched
    # and scanned quickly; set by the warehouse service from the parent codes.
    location_code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    max_weight_kg: Mapped[Decimal] = mapped_column(ScaledDecimal(scale=3), nullable=False)
    max_volume_cm3: Mapped[int] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)

    shelf: Mapped[Shelf] = relationship(back_populates="bins")

    def __repr__(self) -> str:
        return f"<Bin {self.location_code}>"
