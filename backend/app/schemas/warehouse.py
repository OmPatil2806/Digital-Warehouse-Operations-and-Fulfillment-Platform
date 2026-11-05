"""Request and response schemas for the warehouse layout.

Code formats (letters are stored in upper case):
    warehouse WH + 2-4 digits   (WH01)      zone  Z + 1-2 letters (ZA)
    rack      R + 2-3 digits    (R05)       shelf S + 2 digits    (S03)
    bin       B + 2-3 digits    (B08)
Codes cannot be changed after creation: location codes are printed on physical labels.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.models.warehouse import ZoneType


def _normalise_code(value: object) -> object:
    # Runs BEFORE the pattern check, so " za " is accepted and stored as "ZA".
    return value.strip().upper() if isinstance(value, str) else value


def _code(pattern: str, example: str) -> object:
    return Annotated[
        str,
        BeforeValidator(_normalise_code),
        StringConstraints(pattern=pattern),
        Field(examples=[example], description=f"Format like {example}"),
    ]


WarehouseCode = _code(r"^WH\d{2,4}$", "WH01")
ZoneCode = _code(r"^Z[A-Z]{1,2}$", "ZA")
RackCode = _code(r"^R\d{2,3}$", "R05")
ShelfCode = _code(r"^S\d{2}$", "S03")
BinCode = _code(r"^B\d{2,3}$", "B08")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Distance = Annotated[
    Decimal,
    Field(ge=0, le=10_000, decimal_places=1),
    AfterValidator(lambda value: value.quantize(Decimal("0.1"))),
]
MaxWeight = Annotated[
    Decimal,
    Field(gt=0, le=100_000, decimal_places=3),
    AfterValidator(lambda value: value.quantize(Decimal("0.001"))),
]
MaxVolume = Annotated[int, Field(gt=0, le=1_000_000_000, description="cm³")]


# ------------------------------------------------------------------- create/update
class WarehouseCreate(BaseModel):
    code: WarehouseCode
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None


class WarehouseUpdate(BaseModel):
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    is_active: bool | None = None


class ZoneCreate(BaseModel):
    code: ZoneCode
    name: Name
    zone_type: ZoneType


class ZoneUpdate(BaseModel):
    name: Name | None = None
    zone_type: ZoneType | None = None
    is_active: bool | None = None


class RackCreate(BaseModel):
    code: RackCode
    distance_to_packing_m: Distance = Decimal("0.0")


class RackUpdate(BaseModel):
    distance_to_packing_m: Distance | None = None
    is_active: bool | None = None


class ShelfCreate(BaseModel):
    code: ShelfCode
    level: Annotated[int, Field(ge=1, le=50)]


class ShelfUpdate(BaseModel):
    is_active: bool | None = None


class BinCreate(BaseModel):
    code: BinCode
    max_weight_kg: MaxWeight
    max_volume_cm3: MaxVolume


class BinUpdate(BaseModel):
    max_weight_kg: MaxWeight | None = None
    max_volume_cm3: MaxVolume | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------- generation
MAX_GENERATED_BINS = 5_000


class GenerateLayoutRequest(BaseModel):
    """Create `racks` racks x `shelves_per_rack` shelves x `bins_per_shelf` bins in a zone.

    New racks are numbered after the highest existing rack number in the zone. Rack i gets
    distance `first_rack_distance_m + i * distance_step_m` to the packing station.
    """

    racks: Annotated[int, Field(ge=1, le=99)]
    shelves_per_rack: Annotated[int, Field(ge=1, le=20)]
    bins_per_shelf: Annotated[int, Field(ge=1, le=99)]
    max_weight_kg: MaxWeight
    max_volume_cm3: MaxVolume
    first_rack_distance_m: Distance = Decimal("5.0")
    distance_step_m: Distance = Decimal("2.0")

    @property
    def total_bins(self) -> int:
        return self.racks * self.shelves_per_rack * self.bins_per_shelf

    @model_validator(mode="after")
    def _limit_size(self) -> "GenerateLayoutRequest":
        if self.total_bins > MAX_GENERATED_BINS:
            raise ValueError(
                f"At most {MAX_GENERATED_BINS} bins per request (requested {self.total_bins})"
            )
        return self


class GenerateLayoutResponse(BaseModel):
    racks_created: int
    shelves_created: int
    bins_created: int
    first_location_code: str
    last_location_code: str


# ------------------------------------------------------------------------ responses
class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WarehouseResponse(_Base):
    id: int
    code: str
    name: str
    address: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ZoneResponse(_Base):
    id: int
    warehouse_id: int
    code: str
    name: str
    zone_type: ZoneType
    is_active: bool


class RackResponse(_Base):
    id: int
    zone_id: int
    code: str
    distance_to_packing_m: Decimal
    is_active: bool


class ShelfResponse(_Base):
    id: int
    rack_id: int
    code: str
    level: int
    is_active: bool


class BinResponse(_Base):
    id: int
    shelf_id: int
    code: str
    location_code: str
    max_weight_kg: Decimal
    max_volume_cm3: int
    is_active: bool


class BinDetailResponse(BinResponse):
    """A bin with its full path, e.g. for the result of a scan."""

    warehouse: WarehouseResponse
    zone: ZoneResponse
    rack: RackResponse
    shelf: ShelfResponse


class CapacityTotals(BaseModel):
    bins: int = 0
    active_bins: int = 0
    max_weight_kg: Decimal = Decimal("0.000")  # sum over active bins
    max_volume_cm3: int = 0  # sum over active bins


# Layout tree (GET /warehouses/{id}/layout)
class LayoutShelf(ShelfResponse):
    bins: list[BinResponse]


class LayoutRack(RackResponse):
    shelves: list[LayoutShelf]


class LayoutZone(ZoneResponse):
    totals: CapacityTotals
    racks: list[LayoutRack]


class WarehouseLayout(WarehouseResponse):
    totals: CapacityTotals
    zones: list[LayoutZone]


# Capacity check (GET /bins/{id}/fit)
class FitResult(BaseModel):
    fits: bool
    reasons: list[str]  # why it does not fit (empty when it fits)
    required_weight_kg: Decimal
    required_volume_cm3: Decimal
    max_weight_kg: Decimal
    max_volume_cm3: int
    # What is already stored in the bin (counted in the check)
    used_weight_kg: Decimal = Decimal("0")
    used_volume_cm3: Decimal = Decimal("0")
