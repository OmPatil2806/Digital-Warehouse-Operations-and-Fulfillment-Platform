"""Responses and requests of the ML endpoints (/api/v1/ml)."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.ml_results import DecisionStatus, MovementClass, RiskLevel
from app.schemas.common import Page


class ProductRef(BaseModel):
    id: int
    sku: str
    name: str


class ModelSummary(BaseModel):
    """The selected model of a use case and how it did on the test period."""

    use_case: str
    model_name: str
    version: str
    is_baseline: bool
    dataset_version: str
    trained_at: datetime
    test_metrics: dict[str, float]
    scored_at: datetime | None  # latest predictions of this use case (None: not scored)
    as_of: date | None
    predictions: int  # rows of the latest scoring run


class ScoringInfo(BaseModel):
    model_name: str
    is_baseline: bool
    scored_at: datetime
    as_of: date


# ------------------------------------------------------------------------- demand
class ForecastDay(BaseModel):
    day: date
    expected_units: float
    low_units: float
    high_units: float


class ForecastTotal(BaseModel):
    days: int
    expected_units: float
    low_units: float  # sum of daily lows: a cautious lower bound
    high_units: float


class DemandForecastResponse(BaseModel):
    product: ProductRef
    scoring: ScoringInfo | None  # None: not scored yet
    days: list[ForecastDay]
    totals: list[ForecastTotal]  # 7, 14 and 30 days


# ------------------------------------------------------------------------ reorder
class Decision(BaseModel):
    status: DecisionStatus
    decided_by_id: int | None
    decided_at: datetime | None
    decision_note: str | None


class ReorderRecommendationResponse(Decision):
    id: int
    product: ProductRef
    warehouse_id: int
    warehouse_code: str
    probability: float
    priority: RiskLevel
    reorder_date: date
    quantity: int
    reasons: list[str]
    purchase_order_id: int | None
    scored_at: datetime
    as_of: date


ReorderRecommendationPage = Page[ReorderRecommendationResponse]


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


# ----------------------------------------------------------------------- movement
class MovementResponse(BaseModel):
    product: ProductRef
    movement_class: MovementClass
    picks_per_day: float
    scored_at: datetime
    as_of: date


MovementPage = Page[MovementResponse]


class MovementSummary(BaseModel):
    """How many products are fast, medium and slow, and their share of picks."""

    scoring: ScoringInfo | None
    counts: dict[str, int]
    pick_share: dict[str, float]


# ----------------------------------------------------------------------- slotting
class BinRef(BaseModel):
    id: int
    location_code: str
    zone_type: str
    level: int
    distance_to_packing_m: float


class SlottingRecommendationResponse(Decision):
    id: int
    product: ProductRef
    warehouse_id: int
    warehouse_code: str
    current_bin: BinRef | None
    recommended_bin: BinRef
    current_seconds_per_day: float | None
    recommended_seconds_per_day: float
    seconds_saved_per_day: float | None
    scored_at: datetime
    as_of: date


SlottingRecommendationPage = Page[SlottingRecommendationResponse]


# -------------------------------------------------------------------------- delay
class DelayRiskResponse(BaseModel):
    order_id: int
    order_number: str
    shipment_id: int
    probability: float
    risk_level: RiskLevel
    reasons: list[str]
    scored_at: datetime
    as_of: date


DelayRiskPage = Page[DelayRiskResponse]


class OrderDelayRisk(BaseModel):
    order_id: int
    prediction: DelayRiskResponse | None  # None: no prediction (not on its way)


# ------------------------------------------------------------------ recommendation
class RecommendedProduct(BaseModel):
    rank: int
    product: ProductRef
    score: float


class ProductRecommendationsResponse(BaseModel):
    product: ProductRef
    scoring: ScoringInfo | None
    items: list[RecommendedProduct]


class MLSummary(BaseModel):
    """Headline numbers of the latest predictions (dashboard)."""

    as_of: date | None  # None: nothing scored yet
    stockouts_high: int  # pending reorder recommendations with high priority
    stockouts_pending: int
    orders_high_risk: int  # shipments on their way with a high delay risk
    orders_at_risk: int  # high or medium
    orders_on_the_way: int
    forecast_units_7_days: float  # all products, expected
    forecast_units_30_days: float
    slotting_pending: int
    slotting_seconds_saved_per_day: float
