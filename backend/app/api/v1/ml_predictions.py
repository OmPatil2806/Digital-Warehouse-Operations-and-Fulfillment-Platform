"""ML predictions (project document 13, Phase 9). Read from the prediction tables that the
offline scoring step fills; managers decide on reorder and slotting recommendations.

| Data / action                                   | Who                               |
|-------------------------------------------------|-----------------------------------|
| Models, forecasts, movement, slotting, reorder, | admin, manager, staff             |
| delay risk                                      |                                   |
| Approve / reject a recommendation               | admin, manager (audited)          |
| Product recommendations                         | every logged-in user (customers:  |
|                                                 | active products only)             |
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.api.v1.access import MasterDataEditor, WarehouseReader, is_warehouse_user
from app.models.ml_results import DecisionStatus, MovementClass, RiskLevel
from app.schemas import ml as schemas
from app.services.ml_service import MLService

router = APIRouter(
    prefix="/ml",
    tags=["ML predictions"],
    responses={401: {"description": "Not authenticated"}},
)
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=200)]
NOT_FOUND = {404: {"description": "Not found"}}
DECISION = {
    404: {"description": "Recommendation not found"},
    409: {"description": "Already decided"},
}


@router.get("/models", response_model=list[schemas.ModelSummary], summary="Selected models")
def models(db: DbSession, user: WarehouseReader) -> list[schemas.ModelSummary]:
    return MLService(db).models()


@router.get(
    "/demand-forecasts/{product_id}",
    response_model=schemas.DemandForecastResponse,
    summary="Demand forecast of a product (next 30 days, with range)",
    responses=NOT_FOUND,
)
def demand_forecast(
    product_id: int, db: DbSession, user: WarehouseReader
) -> schemas.DemandForecastResponse:
    return MLService(db).demand_forecast(product_id)


@router.get(
    "/reorder-recommendations",
    response_model=schemas.ReorderRecommendationPage,
    summary="Products at risk of running out (latest scoring, highest risk first)",
)
def reorder_recommendations(
    db: DbSession,
    user: WarehouseReader,
    status_: Annotated[DecisionStatus | None, Query(alias="status")] = None,
    priority: RiskLevel | None = None,
    warehouse_id: int | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> schemas.ReorderRecommendationPage:
    items, total = MLService(db).reorder_recommendations(
        status=status_, priority=priority, warehouse_id=warehouse_id, offset=offset, limit=limit
    )
    return schemas.ReorderRecommendationPage(items=items, total=total, offset=offset, limit=limit)


@router.post(
    "/reorder-recommendations/{recommendation_id}/approve",
    response_model=schemas.ReorderRecommendationResponse,
    summary="Approve a reorder recommendation",
    responses=DECISION,
)
def approve_reorder(
    recommendation_id: int,
    db: DbSession,
    user: MasterDataEditor,
    body: schemas.DecisionRequest | None = None,
) -> schemas.ReorderRecommendationResponse:
    note = body.note if body else None
    return MLService(db).decide_reorder(recommendation_id, approve=True, user=user, note=note)


@router.post(
    "/reorder-recommendations/{recommendation_id}/reject",
    response_model=schemas.ReorderRecommendationResponse,
    summary="Reject a reorder recommendation",
    responses=DECISION,
)
def reject_reorder(
    recommendation_id: int,
    db: DbSession,
    user: MasterDataEditor,
    body: schemas.DecisionRequest | None = None,
) -> schemas.ReorderRecommendationResponse:
    note = body.note if body else None
    return MLService(db).decide_reorder(recommendation_id, approve=False, user=user, note=note)


@router.get(
    "/movement-classification/{product_id}",
    response_model=schemas.MovementResponse,
    summary="Fast, medium or slow mover",
    responses=NOT_FOUND,
)
def movement(product_id: int, db: DbSession, user: WarehouseReader) -> schemas.MovementResponse:
    return MLService(db).movement(product_id)


@router.get(
    "/movement-classifications",
    response_model=schemas.MovementPage,
    summary="Movement classes (latest scoring, most picked first)",
)
def movements(
    db: DbSession,
    user: WarehouseReader,
    movement_class: MovementClass | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> schemas.MovementPage:
    items, total = MLService(db).movements(
        movement_class=movement_class, offset=offset, limit=limit
    )
    return schemas.MovementPage(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/movement-classifications/summary",
    response_model=schemas.MovementSummary,
    summary="Number of fast, medium and slow movers and their share of picks",
)
def movement_summary(db: DbSession, user: WarehouseReader) -> schemas.MovementSummary:
    return MLService(db).movement_summary()


@router.get(
    "/slotting-recommendations",
    response_model=schemas.SlottingRecommendationPage,
    summary="Better pick locations (latest scoring, biggest time saving first)",
)
def slotting_recommendations(
    db: DbSession,
    user: WarehouseReader,
    status_: Annotated[DecisionStatus | None, Query(alias="status")] = None,
    warehouse_id: int | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> schemas.SlottingRecommendationPage:
    items, total = MLService(db).slotting_recommendations(
        status=status_, warehouse_id=warehouse_id, offset=offset, limit=limit
    )
    return schemas.SlottingRecommendationPage(items=items, total=total, offset=offset, limit=limit)


@router.post(
    "/slotting-recommendations/{recommendation_id}/approve",
    response_model=schemas.SlottingRecommendationResponse,
    summary="Approve a slotting recommendation",
    responses=DECISION,
)
def approve_slotting(
    recommendation_id: int,
    db: DbSession,
    user: MasterDataEditor,
    body: schemas.DecisionRequest | None = None,
) -> schemas.SlottingRecommendationResponse:
    note = body.note if body else None
    return MLService(db).decide_slotting(recommendation_id, approve=True, user=user, note=note)


@router.post(
    "/slotting-recommendations/{recommendation_id}/reject",
    response_model=schemas.SlottingRecommendationResponse,
    summary="Reject a slotting recommendation",
    responses=DECISION,
)
def reject_slotting(
    recommendation_id: int,
    db: DbSession,
    user: MasterDataEditor,
    body: schemas.DecisionRequest | None = None,
) -> schemas.SlottingRecommendationResponse:
    note = body.note if body else None
    return MLService(db).decide_slotting(recommendation_id, approve=False, user=user, note=note)


@router.get(
    "/delay-risk/{order_id}",
    response_model=schemas.OrderDelayRisk,
    summary="Late-delivery risk of an order's shipment (null when not on its way)",
    responses=NOT_FOUND,
)
def delay_risk(order_id: int, db: DbSession, user: WarehouseReader) -> schemas.OrderDelayRisk:
    return MLService(db).order_delay_risk(order_id)


@router.get(
    "/delay-risks",
    response_model=schemas.DelayRiskPage,
    summary="Shipments on their way by delay risk (latest scoring, highest first)",
)
def delay_risks(
    db: DbSession,
    user: WarehouseReader,
    risk_level: RiskLevel | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> schemas.DelayRiskPage:
    items, total = MLService(db).delay_risks(risk_level=risk_level, offset=offset, limit=limit)
    return schemas.DelayRiskPage(items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/product-recommendations/{product_id}",
    response_model=schemas.ProductRecommendationsResponse,
    summary="Products often bought together with this one",
    responses=NOT_FOUND,
)
def product_recommendations(
    product_id: int, db: DbSession, user: CurrentUser
) -> schemas.ProductRecommendationsResponse:
    return MLService(db).product_recommendations(
        product_id, active_only=not is_warehouse_user(user)
    )
