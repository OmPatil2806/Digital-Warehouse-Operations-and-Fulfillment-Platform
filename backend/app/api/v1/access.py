"""Who may read and change master data (catalog and warehouse layout).

| Data                         | Read                         | Change          |
|------------------------------|------------------------------|-----------------|
| Categories, products         | every logged-in user (*)     | admin, manager  |
| Suppliers, supplier products | admin, manager, staff        | admin, manager  |
| Warehouse layout             | admin, manager, staff        | admin, manager  |

(*) Customers only see active records, and products without costs or margins.
"""

from typing import Annotated

from fastapi import Depends

from app.core.permissions import require_roles
from app.models.user import RoleName, User

# require_roles always lets admins in as well.
MasterDataEditor = Annotated[User, Depends(require_roles(RoleName.MANAGER))]
WarehouseReader = Annotated[User, Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))]

CatalogEditor = MasterDataEditor  # readable name for catalog endpoints
LayoutEditor = MasterDataEditor  # readable name for warehouse layout endpoints


def is_warehouse_user(user: User) -> bool:
    """Admins, managers and staff see full product data and archived records."""
    return user.has_role(RoleName.ADMIN, RoleName.MANAGER, RoleName.STAFF)
