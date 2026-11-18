"""Prediction results of the selected ML models (project document 10 "ML results").

The offline scoring step (scripts/score_models.py) runs each use case's selected model
with the same feature code as in training and stores what it predicts here; the
application only reads these tables. Every scoring run adds new rows (`scored_at`), so
earlier predictions stay available to compare with what really happened. The latest
run of a use case is what the application shows.

Reorder and slotting recommendations carry a manager's decision (pending, approved or
rejected, by whom and when).
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.mixins import IdMixin, one_of


class DecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MovementClass(StrEnum):
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class _Prediction(IdMixin):
    """Columns every prediction has: which model, when it was scored, for which day."""

    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    scored_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)  # last day of known data


class _Decision:
    """A manager's decision on a recommendation."""

    status: Mapped[str] = mapped_column(
        String(20), default=DecisionStatus.PENDING, server_default="pending", nullable=False
    )
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str | None] = mapped_column(String(500))


class DemandForecast(_Prediction, Base):
    """Expected units of a product on one forecast day, with an 80 % range."""

    __tablename__ = "demand_forecasts"
    __table_args__ = (
        Index("ix_demand_forecasts_product_scored", "product_id", "scored_at"),
        CheckConstraint("low_units >= 0 AND low_units <= expected_units", name="low"),
        CheckConstraint("high_units >= expected_units", name="high"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    expected_units: Mapped[float] = mapped_column(nullable=False)
    low_units: Mapped[float] = mapped_column(nullable=False)
    high_units: Mapped[float] = mapped_column(nullable=False)


class ReorderRecommendation(_Decision, _Prediction, Base):
    """Stockout risk of a product in a warehouse and what to order."""

    __tablename__ = "reorder_recommendations"
    __table_args__ = (
        Index("ix_reorder_recommendations_scored", "scored_at", "probability"),
        CheckConstraint("probability BETWEEN 0 AND 1", name="probability_range"),
        CheckConstraint("quantity >= 0", name="quantity_not_negative"),
        CheckConstraint(one_of("priority", RiskLevel), name="valid_priority"),
        CheckConstraint(one_of("status", DecisionStatus), name="valid_status"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    probability: Mapped[float] = mapped_column(nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    reorder_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL")
    )


class MovementClassification(_Prediction, Base):
    """Fast, medium or slow mover."""

    __tablename__ = "movement_classifications"
    __table_args__ = (
        Index("ix_movement_classifications_product_scored", "product_id", "scored_at"),
        CheckConstraint(one_of("movement_class", MovementClass), name="valid_class"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    movement_class: Mapped[str] = mapped_column(String(10), nullable=False)
    picks_per_day: Mapped[float] = mapped_column(nullable=False)  # recent, for context


class SlottingRecommendation(_Decision, _Prediction, Base):
    """A better pick-face bin for a product in a warehouse."""

    __tablename__ = "slotting_recommendations"
    __table_args__ = (
        Index("ix_slotting_recommendations_scored", "scored_at"),
        CheckConstraint(one_of("status", DecisionStatus), name="valid_status"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    current_bin_id: Mapped[int | None] = mapped_column(ForeignKey("bins.id", ondelete="SET NULL"))
    recommended_bin_id: Mapped[int] = mapped_column(
        ForeignKey("bins.id", ondelete="CASCADE"), nullable=False
    )
    # Estimated seconds of picking per day at the recent pick rate.
    current_seconds_per_day: Mapped[float | None] = mapped_column()
    recommended_seconds_per_day: Mapped[float] = mapped_column(nullable=False)


class DelayPrediction(_Prediction, Base):
    """Risk that a shipment on its way arrives late, with the main reasons."""

    __tablename__ = "delay_predictions"
    __table_args__ = (
        Index("ix_delay_predictions_order_scored", "order_id", "scored_at"),
        CheckConstraint("probability BETWEEN 0 AND 1", name="probability_range"),
        CheckConstraint(one_of("risk_level", RiskLevel), name="valid_risk_level"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    probability: Mapped[float] = mapped_column(nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ProductRecommendation(_Prediction, Base):
    """A product often added to a basket that holds `product_id` (rank 1 = best)."""

    __tablename__ = "product_recommendations"
    __table_args__ = (
        Index("ix_product_recommendations_product_scored", "product_id", "scored_at"),
        CheckConstraint("rank >= 1", name="rank_positive"),
        CheckConstraint("recommended_product_id != product_id", name="not_itself"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    recommended_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(nullable=False)
    score: Mapped[float] = mapped_column(nullable=False)


RESULT_TABLES: dict[str, type[Any]] = {
    "demand_forecasting": DemandForecast,
    "reorder": ReorderRecommendation,
    "movement_classification": MovementClassification,
    "slotting": SlottingRecommendation,
    "delay_prediction": DelayPrediction,
    "recommendation": ProductRecommendation,
}
