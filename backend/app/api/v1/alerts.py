"""Alert endpoints. Warehouse users see alerts; managers and admins handle them."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import DbSession
from app.api.v1.access import MasterDataEditor
from app.core.permissions import require_roles
from app.models.audit import AlertStatus, AlertType
from app.models.user import RoleName
from app.schemas.inventory import AlertPage, AlertResponse
from app.services.alert_service import AlertService

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[Depends(require_roles(RoleName.MANAGER, RoleName.STAFF))],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Warehouse role required"},
    },
)


class AlertSummary(BaseModel):
    unresolved: int  # for the badge in the navigation


@router.get("", response_model=AlertPage, summary="List alerts (newest first)")
def list_alerts(
    db: DbSession,
    status_: Annotated[AlertStatus | None, Query(alias="status")] = None,
    unresolved: Annotated[bool, Query(description="Only open and acknowledged alerts")] = False,
    alert_type: AlertType | None = None,
    product_id: int | None = None,
    bin_id: int | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AlertPage:
    items, total = AlertService(db).search(
        offset=offset,
        limit=limit,
        status=status_,
        unresolved=unresolved,
        alert_type=alert_type,
        product_id=product_id,
        bin_id=bin_id,
    )
    return AlertPage(
        items=[AlertResponse.model_validate(a) for a in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/summary", response_model=AlertSummary, summary="Number of unresolved alerts")
def alert_summary(db: DbSession) -> AlertSummary:
    return AlertSummary(unresolved=AlertService(db).count_unresolved())


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertResponse,
    summary="Acknowledge an alert (someone is on it)",
    responses={404: {"description": "Alert not found"}, 409: {"description": "Not open"}},
)
def acknowledge_alert(alert_id: int, db: DbSession, user: MasterDataEditor) -> AlertResponse:
    return AlertResponse.model_validate(AlertService(db).acknowledge(alert_id, user=user))


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Resolve an alert by hand",
    responses={404: {"description": "Alert not found"}, 409: {"description": "Already resolved"}},
)
def resolve_alert(alert_id: int, db: DbSession, user: MasterDataEditor) -> AlertResponse:
    return AlertResponse.model_validate(AlertService(db).resolve(alert_id, user=user))
