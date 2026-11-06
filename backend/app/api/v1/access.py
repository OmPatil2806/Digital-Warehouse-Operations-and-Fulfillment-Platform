"""Who may read and change master data (catalog and warehouse layout).

| Data                         | Read                         | Change          |
|------------------------------|------------------------------|-----------------|
| Categories, products         | every logged-in user (*)     | admin, manager  |
| Suppliers, supplier products | admin, manager, staff        | admin, manager  |
| Warehouse layout             | admin, manager, staff        | admin, manager  |

(*) Customers only see active records, and products without costs or margins.
"""

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from app.core.permissions import require_roles
from app.models.user import RoleName, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.order import Order

# require_roles always lets admins in as well.
MasterDataEditor = Annotated[User, Depends(require_roles(RoleName.MANAGER))]
WarehouseReader = Annotated[User, Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))]

CatalogEditor = MasterDataEditor  # readable name for catalog endpoints
LayoutEditor = MasterDataEditor  # readable name for warehouse layout endpoints


def is_warehouse_user(user: User) -> bool:
    """Admins, managers and staff see full product data and archived records."""
    return user.has_role(RoleName.ADMIN, RoleName.MANAGER, RoleName.STAFF)


# ------------------------------------------------------------------- orders (Phase 5)
# | Data / action                          | Who                                      |
# |----------------------------------------|------------------------------------------|
# | See orders, shipments, returns         | warehouse roles: all; customers: own     |
# | Place, confirm, cancel an order        | admin, manager; customers: their own     |
# | Hold, release, retry reservation       | admin, manager                           |
# | Allocate, pick, pack, ship, track      | admin, manager, staff                    |
# | Open a return                          | warehouse roles; customers: their own    |
# | Inspect a return, check delays         | warehouse roles / managers               |
# Another customer's records answer 404, so their existence is not revealed.


def is_manager(user: User) -> bool:
    return user.has_role(RoleName.ADMIN, RoleName.MANAGER)


def customer_scope(db: "Session", user: User) -> int | None:
    """None for warehouse roles (everything), else the id of the user's customer."""
    from app.services.customer_service import CustomerService

    return CustomerService(db).scope_for(user)


def visible_order(db: "Session", order_id: int, user: User) -> "Order":
    """The order if the user may see it; otherwise 404."""
    from app.services.order_service import OrderNotFoundError, OrderService

    order = OrderService(db).get(order_id)
    scope = customer_scope(db, user)
    if scope is not None and order.customer_id != scope:
        raise OrderNotFoundError()
    return order


def require_manager_or_owner(db: "Session", order: "Order", user: User) -> None:
    """Managers act on every order; customers only on their own; staff not at all."""
    from app.exceptions import PermissionDeniedError

    if is_manager(user):
        return
    if user.has_role(RoleName.STAFF) or customer_scope(db, user) != order.customer_id:
        raise PermissionDeniedError("Only managers or the ordering customer can do this")
