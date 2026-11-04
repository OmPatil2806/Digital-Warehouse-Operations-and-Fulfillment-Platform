"""Product endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import CatalogEditor, WarehouseReader, is_warehouse_user
from app.models.catalog import Product
from app.schemas.catalog import (
    ProductCreate,
    ProductPublicResponse,
    ProductResponse,
    ProductSort,
    ProductUpdate,
    SupplierProductResponse,
)
from app.schemas.common import Page
from app.services.catalog_service import ProductService, SupplierProductService

router = APIRouter(prefix="/products", tags=["Products"])


def _for(user_is_warehouse: bool, product: Product) -> ProductResponse | ProductPublicResponse:
    model = ProductResponse if user_is_warehouse else ProductPublicResponse
    return model.model_validate(product)


@router.get(
    "",
    response_model=Page[ProductResponse] | Page[ProductPublicResponse],
    summary="List and search products",
    description=(
        "Customers only see active products and no cost/margin fields. "
        "`category_id` includes products in all sub-categories."
    ),
)
def list_products(
    db: DbSession,
    user: CurrentUser,
    q: Annotated[
        str | None, Query(max_length=100, description="Search SKU, name, brand, barcode")
    ] = None,
    category_id: int | None = None,
    supplier_id: Annotated[
        int | None, Query(description="Products this supplier offers or supplies by default")
    ] = None,
    is_active: bool | None = None,
    sort: ProductSort = "sku",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[ProductResponse] | Page[ProductPublicResponse]:
    warehouse = is_warehouse_user(user)
    if not warehouse:
        is_active = True
        supplier_id = None  # supplier relations are internal information
    products, total = ProductService(db).search(
        q=q,
        category_id=category_id,
        supplier_id=supplier_id,
        is_active=is_active,
        sort=sort,
        offset=offset,
        limit=limit,
    )
    items = [_for(warehouse, product) for product in products]
    page_model = Page[ProductResponse] if warehouse else Page[ProductPublicResponse]
    return page_model(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/{product_id}",
    response_model=ProductResponse | ProductPublicResponse,
    summary="Get a product",
)
def get_product(
    product_id: int, db: DbSession, user: CurrentUser
) -> ProductResponse | ProductPublicResponse:
    warehouse = is_warehouse_user(user)
    product = ProductService(db).get(product_id, active_only=not warehouse)
    return _for(warehouse, product)


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
)
def create_product(data: ProductCreate, db: DbSession, _: CatalogEditor) -> ProductResponse:
    return ProductResponse.model_validate(ProductService(db).create(data))


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update, archive (is_active=false) or restore a product",
)
def update_product(
    product_id: int, data: ProductUpdate, db: DbSession, _: CatalogEditor
) -> ProductResponse:
    return ProductResponse.model_validate(ProductService(db).update(product_id, data))


@router.get(
    "/{product_id}/suppliers",
    response_model=list[SupplierProductResponse],
    summary="Suppliers offering this product (preferred first)",
)
def product_suppliers(
    product_id: int, db: DbSession, _: WarehouseReader
) -> list[SupplierProductResponse]:
    links = SupplierProductService(db).for_product(product_id)
    return [SupplierProductResponse.model_validate(link) for link in links]
