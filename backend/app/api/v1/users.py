"""User management endpoints (admin only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession
from app.core.permissions import require_roles
from app.models.user import RoleName, User
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate
from app.services.user_service import UserService

AdminUser = Annotated[User, Depends(require_roles(RoleName.ADMIN))]

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(require_roles(RoleName.ADMIN))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
    },
)

NOT_FOUND = {404: {"description": "User not found"}}
CONFLICT = {409: {"description": "Email already exists or a safety rule was violated"}}


@router.get("", response_model=UserListResponse, summary="List users")
def list_users(
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UserListResponse:
    users, total = UserService(db).list_users(offset=offset, limit=limit)
    return UserListResponse(
        items=[UserResponse.model_validate(user) for user in users],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    responses=CONFLICT,
)
def create_user(data: UserCreate, db: DbSession) -> UserResponse:
    return UserResponse.model_validate(UserService(db).create_user(data))


@router.get("/{user_id}", response_model=UserResponse, summary="Get a user", responses=NOT_FOUND)
def get_user(user_id: int, db: DbSession) -> UserResponse:
    return UserResponse.model_validate(UserService(db).get_user(user_id))


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update a user (only the fields sent are changed)",
    responses={**NOT_FOUND, **CONFLICT},
)
def update_user(user_id: int, data: UserUpdate, db: DbSession, admin: AdminUser) -> UserResponse:
    user = UserService(db).update_user(user_id, data, acting_user=admin)
    return UserResponse.model_validate(user)


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate a user and end all their sessions",
    responses={**NOT_FOUND, **CONFLICT},
)
def deactivate_user(user_id: int, db: DbSession, admin: AdminUser) -> UserResponse:
    user = UserService(db).deactivate_user(user_id, acting_user=admin)
    return UserResponse.model_validate(user)
