"""Category endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.catalog_access import CatalogEditor, is_warehouse_user
from app.exceptions import NotFoundError
from app.models.catalog import Category
from app.schemas.catalog import CategoryCreate, CategoryResponse, CategoryUpdate
from app.schemas.common import Page
from app.services.catalog_service import CategoryService

router = APIRouter(prefix="/categories", tags=["Categories"])


def _response(category: Category, product_count: int | None = None) -> CategoryResponse:
    response = CategoryResponse.model_validate(category)
    if product_count is None:
        return response
    return response.model_copy(update={"product_count": product_count})


@router.get("", response_model=Page[CategoryResponse], summary="List categories")
def list_categories(
    db: DbSession,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=80, description="Search in names")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by status")] = None,
    parent_id: Annotated[int | None, Query(description="Only direct children of")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[CategoryResponse]:
    if not is_warehouse_user(user):
        is_active = True  # customers never see archived categories
    rows, total = CategoryService(db).search(
        q=q, is_active=is_active, parent_id=parent_id, offset=offset, limit=limit
    )
    return Page(
        items=[_response(category, count) for category, count in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{category_id}", response_model=CategoryResponse, summary="Get a category")
def get_category(category_id: int, db: DbSession, user: CurrentUser) -> CategoryResponse:
    service = CategoryService(db)
    category = service.get(category_id)
    if not category.is_active and not is_warehouse_user(user):
        raise NotFoundError("Category not found")
    return _response(category, service.categories.count_active_products(category.id))


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
)
def create_category(data: CategoryCreate, db: DbSession, _: CatalogEditor) -> CategoryResponse:
    return _response(CategoryService(db).create(data), 0)


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Update, archive (is_active=false) or restore a category",
)
def update_category(
    category_id: int, data: CategoryUpdate, db: DbSession, _: CatalogEditor
) -> CategoryResponse:
    service = CategoryService(db)
    category = service.update(category_id, data)
    return _response(category, service.categories.count_active_products(category.id))
