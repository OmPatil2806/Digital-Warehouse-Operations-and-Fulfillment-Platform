"""Dashboard KPIs (project document, section 9.4).

| Dashboard   | Who                   | Money values        |
|-------------|-----------------------|---------------------|
| Overview    | admin, manager, staff | admin, manager only |
| Inventory   | admin, manager, staff | admin, manager only |
| Fulfillment | admin, manager, staff | (none)              |
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.api.v1.access import WarehouseReader, is_manager
from app.schemas.dashboard import FulfillmentDashboard, InventoryDashboard, OverviewDashboard
from app.services.dashboard_service import DashboardService, DateRange

router = APIRouter(
    prefix="/dashboards",
    tags=["Dashboards"],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Warehouse role required"},
        422: {"description": "Invalid date range"},
    },
)

DateFrom = Annotated[
    date | None, Query(description="First day (UTC), default: 29 days before date_to")
]
DateTo = Annotated[date | None, Query(description="Last day (UTC), default: today")]


@router.get("/overview", response_model=OverviewDashboard, summary="Headline KPIs")
def overview(
    db: DbSession,
    user: WarehouseReader,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> OverviewDashboard:
    period = DateRange.resolve(date_from, date_to)
    return DashboardService(db).overview(period, include_financials=is_manager(user))


@router.get(
    "/inventory",
    response_model=InventoryDashboard,
    summary="Stock value, status, turnover and days of supply",
)
def inventory(
    db: DbSession,
    user: WarehouseReader,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Products to list")] = 100,
) -> InventoryDashboard:
    period = DateRange.resolve(date_from, date_to)
    return DashboardService(db).inventory(period, include_financials=is_manager(user), limit=limit)


@router.get(
    "/fulfillment",
    response_model=FulfillmentDashboard,
    summary="Orders per day, fulfillment speed, on-time delivery, picking accuracy",
)
def fulfillment(
    db: DbSession,
    _: WarehouseReader,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> FulfillmentDashboard:
    return DashboardService(db).fulfillment(DateRange.resolve(date_from, date_to))
