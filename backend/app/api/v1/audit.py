"""Audit log endpoint (admin only, read only: audit rows can never be changed)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession
from app.core.permissions import require_roles
from app.models.user import RoleName
from app.schemas.audit import AuditLogPage, AuditLogResponse
from app.services.audit_service import AuditService

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit"],
    dependencies=[Depends(require_roles(RoleName.ADMIN))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Admin role required"},
    },
)


def _as_utc(value: datetime | None) -> datetime | None:
    """Times sent without a timezone are taken as UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@router.get("", response_model=AuditLogPage, summary="Search the audit log (newest first)")
def list_audit_logs(
    db: DbSession,
    entity_type: Annotated[
        str | None, Query(max_length=40, description="e.g. product, bin, user")
    ] = None,
    entity_id: int | None = None,
    actor_id: Annotated[int | None, Query(description="Only changes made by this user")] = None,
    action: Annotated[
        str | None, Query(max_length=40, description="create, update, delete, ...")
    ] = None,
    since: Annotated[datetime | None, Query(description="From this time (inclusive)")] = None,
    until: Annotated[datetime | None, Query(description="Until this time (exclusive)")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditLogPage:
    items, total = AuditService(db).search(
        offset=offset,
        limit=limit,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        since=_as_utc(since),
        until=_as_utc(until),
    )
    return AuditLogPage(
        items=[AuditLogResponse.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )
