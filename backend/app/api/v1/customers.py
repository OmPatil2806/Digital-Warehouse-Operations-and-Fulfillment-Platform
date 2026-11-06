"""Customer endpoints. Warehouse roles read customers; managers create and change them."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader
from app.exceptions import NotFoundError
from app.repositories.order_repository import OrderRepository
from app.schemas.order import CustomerCreate, CustomerPage, CustomerResponse, CustomerUpdate
from app.services.customer_service import CustomerService

router = APIRouter(
    prefix="/customers",
    tags=["Customers"],
    responses={401: {"description": "Not authenticated"}, 403: {"description": "Not allowed"}},
)


@router.get("", response_model=CustomerPage, summary="List customers")
def list_customers(
    db: DbSession,
    _: WarehouseReader,
    q: Annotated[str | None, Query(max_length=100, description="Code, name or email")] = None,
    is_active: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CustomerPage:
    items, total = OrderRepository(db).search_customers(
        offset=offset, limit=limit, q=q, is_active=is_active
    )
    return CustomerPage(
        items=[CustomerResponse.model_validate(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/me", response_model=CustomerResponse, summary="The customer of the logged-in user")
def my_customer(db: DbSession, user: CurrentUser) -> CustomerResponse:
    customer = CustomerService(db).for_user(user)
    if customer is None:
        raise NotFoundError("Your login is not linked to a customer")
    return CustomerResponse.model_validate(customer)


@router.post(
    "", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED, summary="Create"
)
def create_customer(data: CustomerCreate, db: DbSession, _: MasterDataEditor) -> CustomerResponse:
    return CustomerResponse.model_validate(CustomerService(db).create(data))


@router.get("/{customer_id}", response_model=CustomerResponse, summary="Get a customer")
def get_customer(customer_id: int, db: DbSession, _: WarehouseReader) -> CustomerResponse:
    return CustomerResponse.model_validate(CustomerService(db).get(customer_id))


@router.patch("/{customer_id}", response_model=CustomerResponse, summary="Change a customer")
def update_customer(
    customer_id: int, data: CustomerUpdate, db: DbSession, _: MasterDataEditor
) -> CustomerResponse:
    return CustomerResponse.model_validate(CustomerService(db).update(customer_id, data))
