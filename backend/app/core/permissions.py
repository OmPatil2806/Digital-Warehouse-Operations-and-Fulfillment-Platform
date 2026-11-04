"""Role-based access control for endpoints.

Usage:
    @router.get("/reports", dependencies=[Depends(require_roles(RoleName.MANAGER))])
    def reports(): ...

    # or, when the endpoint also needs the user object:
    @router.post("/users")
    def create_user(admin: Annotated[User, Depends(require_roles(RoleName.ADMIN))]): ...

Admins are allowed everywhere: `require_roles(RoleName.MANAGER)` also lets admins in.
"""

from collections.abc import Callable

from fastapi import HTTPException, status

from app.api.deps import CurrentUser
from app.models.user import RoleName, User

FORBIDDEN_MESSAGE = "You do not have permission to perform this action"


def require_roles(*roles: RoleName) -> Callable[[User], User]:
    """Dependency factory: allow only users with at least one of `roles` (or admin)."""
    if not roles:
        raise ValueError("require_roles() needs at least one role")
    allowed = {RoleName.ADMIN, *roles}

    def _check_roles(user: CurrentUser) -> User:
        if not user.has_role(*allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_MESSAGE)
        return user

    return _check_roles
