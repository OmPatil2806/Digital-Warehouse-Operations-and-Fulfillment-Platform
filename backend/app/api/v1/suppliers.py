"""Supplier endpoints, including the products each supplier offers."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbSession
from app.api.v1.access import CatalogEditor, WarehouseReader
from app.schemas.catalog import (
    SupplierCreate,
    SupplierProductCreate,
    SupplierProductResponse,
    SupplierProductUpdate,
    SupplierResponse,
    SupplierSort,
    SupplierUpdate,
)
from app.schemas.common import Page
from app.services.catalog_service import SupplierProductService, SupplierService

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("", response_model=Page[SupplierResponse], summary="List and search suppliers")
def list_suppliers(
    db: DbSession,
    _: WarehouseReader,
    q: Annotated[
        str | None, Query(max_length=100, description="Search code, name, email, country")
    ] = None,
    is_active: bool | None = None,
    sort: SupplierSort = "code",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[SupplierResponse]:
    suppliers, total = SupplierService(db).search(
        q=q, is_active=is_active, sort=sort, offset=offset, limit=limit
    )
    return Page(
        items=[SupplierResponse.model_validate(s) for s in suppliers],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{supplier_id}", response_model=SupplierResponse, summary="Get a supplier")
def get_supplier(supplier_id: int, db: DbSession, _: WarehouseReader) -> SupplierResponse:
    return SupplierResponse.model_validate(SupplierService(db).get(supplier_id))


@router.post(
    "",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a supplier",
)
def create_supplier(data: SupplierCreate, db: DbSession, _: CatalogEditor) -> SupplierResponse:
    return SupplierResponse.model_validate(SupplierService(db).create(data))


@router.patch(
    "/{supplier_id}",
    response_model=SupplierResponse,
    summary="Update, archive (is_active=false) or restore a supplier",
)
def update_supplier(
    supplier_id: int, data: SupplierUpdate, db: DbSession, _: CatalogEditor
) -> SupplierResponse:
    return SupplierResponse.model_validate(SupplierService(db).update(supplier_id, data))


# --------------------------------------------------------------------- products of a supplier
@router.get(
    "/{supplier_id}/products",
    response_model=list[SupplierProductResponse],
    summary="Products offered by this supplier",
)
def supplier_products(
    supplier_id: int, db: DbSession, _: WarehouseReader
) -> list[SupplierProductResponse]:
    links = SupplierProductService(db).for_supplier(supplier_id)
    return [SupplierProductResponse.model_validate(link) for link in links]


@router.post(
    "/{supplier_id}/products",
    response_model=SupplierProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product to this supplier's offer",
)
def add_supplier_product(
    supplier_id: int, data: SupplierProductCreate, db: DbSession, _: CatalogEditor
) -> SupplierProductResponse:
    link = SupplierProductService(db).add(supplier_id, data)
    return SupplierProductResponse.model_validate(link)


@router.patch(
    "/{supplier_id}/products/{product_id}",
    response_model=SupplierProductResponse,
    summary="Update the supplier's terms for a product",
)
def update_supplier_product(
    supplier_id: int,
    product_id: int,
    data: SupplierProductUpdate,
    db: DbSession,
    _: CatalogEditor,
) -> SupplierProductResponse:
    link = SupplierProductService(db).update(supplier_id, product_id, data)
    return SupplierProductResponse.model_validate(link)


@router.delete(
    "/{supplier_id}/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a product from this supplier's offer",
)
def remove_supplier_product(
    supplier_id: int, product_id: int, db: DbSession, _: CatalogEditor
) -> Response:
    SupplierProductService(db).remove(supplier_id, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
