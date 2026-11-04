"""Warehouse layout endpoints: warehouses, zones, racks, shelves, bins.

Read: admin, manager, staff. Change: admin, manager. Customers: 403.
Archive or restore any level with PATCH {"is_active": false|true}; archiving a level
also archives everything below it.
"""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession
from app.api.v1.access import LayoutEditor, WarehouseReader
from app.schemas.common import Page
from app.schemas.warehouse import (
    BinCreate,
    BinDetailResponse,
    BinResponse,
    BinUpdate,
    FitResult,
    GenerateLayoutRequest,
    GenerateLayoutResponse,
    RackCreate,
    RackResponse,
    RackUpdate,
    ShelfCreate,
    ShelfResponse,
    ShelfUpdate,
    WarehouseCreate,
    WarehouseLayout,
    WarehouseResponse,
    WarehouseUpdate,
    ZoneCreate,
    ZoneResponse,
    ZoneUpdate,
)
from app.services.warehouse_service import WarehouseService

router = APIRouter(tags=["Warehouse layout"])

CREATED = status.HTTP_201_CREATED


# --------------------------------------------------------------------------- warehouses
@router.get("/warehouses", response_model=list[WarehouseResponse], summary="List warehouses")
def list_warehouses(
    db: DbSession, _: WarehouseReader, is_active: bool | None = None
) -> list[WarehouseResponse]:
    return [
        WarehouseResponse.model_validate(w)
        for w in WarehouseService(db).list_warehouses(is_active=is_active)
    ]


@router.post("/warehouses", response_model=WarehouseResponse, status_code=CREATED)
def create_warehouse(data: WarehouseCreate, db: DbSession, _: LayoutEditor) -> WarehouseResponse:
    return WarehouseResponse.model_validate(WarehouseService(db).create_warehouse(data))


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
def get_warehouse(warehouse_id: int, db: DbSession, _: WarehouseReader) -> WarehouseResponse:
    return WarehouseResponse.model_validate(WarehouseService(db).get_warehouse(warehouse_id))


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
def update_warehouse(
    warehouse_id: int, data: WarehouseUpdate, db: DbSession, _: LayoutEditor
) -> WarehouseResponse:
    service = WarehouseService(db)
    return WarehouseResponse.model_validate(
        service.update(service.get_warehouse(warehouse_id), data)
    )


@router.get(
    "/warehouses/{warehouse_id}/layout",
    response_model=WarehouseLayout,
    summary="Full tree (zones > racks > shelves > bins) with capacity totals",
    description="Racks are ordered by distance to the packing station, shelves by level.",
)
def warehouse_layout(
    warehouse_id: int,
    db: DbSession,
    _: WarehouseReader,
    include_inactive: Annotated[bool, Query(description="Also show archived records")] = False,
) -> WarehouseLayout:
    return WarehouseLayout.model_validate(
        WarehouseService(db).layout(warehouse_id, include_inactive=include_inactive)
    )


# -------------------------------------------------------------------------------- zones
@router.post("/warehouses/{warehouse_id}/zones", response_model=ZoneResponse, status_code=CREATED)
def create_zone(
    warehouse_id: int, data: ZoneCreate, db: DbSession, _: LayoutEditor
) -> ZoneResponse:
    return ZoneResponse.model_validate(WarehouseService(db).create_zone(warehouse_id, data))


@router.patch("/zones/{zone_id}", response_model=ZoneResponse)
def update_zone(zone_id: int, data: ZoneUpdate, db: DbSession, _: LayoutEditor) -> ZoneResponse:
    service = WarehouseService(db)
    return ZoneResponse.model_validate(service.update(service.get_zone(zone_id), data))


@router.post(
    "/zones/{zone_id}/generate",
    response_model=GenerateLayoutResponse,
    status_code=CREATED,
    summary="Generate racks x shelves x bins in one step (all or nothing)",
)
def generate_layout(
    zone_id: int, data: GenerateLayoutRequest, db: DbSession, _: LayoutEditor
) -> GenerateLayoutResponse:
    return WarehouseService(db).generate(zone_id, data)


# ---------------------------------------------------------------------- racks/shelves
@router.post("/zones/{zone_id}/racks", response_model=RackResponse, status_code=CREATED)
def create_rack(zone_id: int, data: RackCreate, db: DbSession, _: LayoutEditor) -> RackResponse:
    return RackResponse.model_validate(WarehouseService(db).create_rack(zone_id, data))


@router.patch("/racks/{rack_id}", response_model=RackResponse)
def update_rack(rack_id: int, data: RackUpdate, db: DbSession, _: LayoutEditor) -> RackResponse:
    service = WarehouseService(db)
    return RackResponse.model_validate(service.update(service.get_rack(rack_id), data))


@router.post("/racks/{rack_id}/shelves", response_model=ShelfResponse, status_code=CREATED)
def create_shelf(rack_id: int, data: ShelfCreate, db: DbSession, _: LayoutEditor) -> ShelfResponse:
    return ShelfResponse.model_validate(WarehouseService(db).create_shelf(rack_id, data))


@router.patch("/shelves/{shelf_id}", response_model=ShelfResponse)
def update_shelf(shelf_id: int, data: ShelfUpdate, db: DbSession, _: LayoutEditor) -> ShelfResponse:
    service = WarehouseService(db)
    return ShelfResponse.model_validate(service.update(service.get_shelf(shelf_id), data))


# --------------------------------------------------------------------------------- bins
@router.post("/shelves/{shelf_id}/bins", response_model=BinResponse, status_code=CREATED)
def create_bin(shelf_id: int, data: BinCreate, db: DbSession, _: LayoutEditor) -> BinResponse:
    return BinResponse.model_validate(WarehouseService(db).create_bin(shelf_id, data))


@router.get("/bins", response_model=Page[BinResponse], summary="Search bins by location code")
def search_bins(
    db: DbSession,
    _: WarehouseReader,
    warehouse_id: int | None = None,
    zone_id: int | None = None,
    q: Annotated[str | None, Query(max_length=60, description="Part of a location code")] = None,
    is_active: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[BinResponse]:
    bins, total = WarehouseService(db).search_bins(
        warehouse_id=warehouse_id,
        zone_id=zone_id,
        q=q,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return Page(
        items=[BinResponse.model_validate(b) for b in bins], total=total, offset=offset, limit=limit
    )


@router.get(
    "/bins/by-code/{location_code}",
    response_model=BinDetailResponse,
    summary="Look up a bin by its location code (simulated barcode scan)",
)
def bin_by_code(location_code: str, db: DbSession, _: WarehouseReader) -> BinDetailResponse:
    bin_ = WarehouseService(db).get_bin_by_code(location_code)
    shelf = bin_.shelf
    rack = shelf.rack
    zone = rack.zone
    return BinDetailResponse.model_validate(
        {
            **BinResponse.model_validate(bin_).model_dump(),
            "warehouse": WarehouseResponse.model_validate(zone.warehouse),
            "zone": ZoneResponse.model_validate(zone),
            "rack": RackResponse.model_validate(rack),
            "shelf": ShelfResponse.model_validate(shelf),
        }
    )


@router.patch("/bins/{bin_id}", response_model=BinResponse)
def update_bin(bin_id: int, data: BinUpdate, db: DbSession, _: LayoutEditor) -> BinResponse:
    service = WarehouseService(db)
    return BinResponse.model_validate(service.update(service.get_bin(bin_id), data))


@router.get(
    "/bins/{bin_id}/fit",
    response_model=FitResult,
    summary="Check whether a quantity of a product fits into an (empty) bin",
)
def check_fit(
    bin_id: int,
    product_id: int,
    db: DbSession,
    _: WarehouseReader,
    quantity: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
) -> FitResult:
    service = WarehouseService(db)
    result = service.check_fit(bin_id, product_id, quantity)
    bin_ = service.get_bin(bin_id)
    return FitResult(
        fits=result.fits,
        reasons=result.reasons,
        required_weight_kg=result.required_weight_kg,
        required_volume_cm3=result.required_volume_cm3,
        max_weight_kg=bin_.max_weight_kg,
        max_volume_cm3=bin_.max_volume_cm3,
    )
