"""Model registry (project document 12.4 and 16.8): every trained model, its metrics and
which one is in use.

- `model_versions`: one row per trained model (baselines included): use case, model
  name, version, the dataset it was trained on, features, hyperparameters, where the
  saved `.keras` file is, and its status. Per use case at most one model is `selected`:
  the one the application uses (Phase 9). Earlier selections become `retired`.
- `model_metrics`: the metric values of a model on the validation and test periods.

Rows are written by the offline training pipeline (ml/registry/register_model.py); the
application only reads them.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime
from app.models.mixins import IdMixin, TimestampMixin, one_of


class UseCase(StrEnum):
    DEMAND = "demand_forecasting"
    REORDER = "reorder"
    MOVEMENT = "movement_classification"
    SLOTTING = "slotting"
    DELAY = "delay_prediction"
    RECOMMENDATION = "recommendation"


class ModelStatus(StrEnum):
    CANDIDATE = "candidate"  # trained and evaluated, not in use
    SELECTED = "selected"  # the best model of its use case: the one the application uses
    RETIRED = "retired"  # was selected before a newer model replaced it


class MetricSplit(StrEnum):
    VALIDATION = "validation"
    TEST = "test"


class ModelVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("use_case", "model_name", "version"),
        CheckConstraint(one_of("use_case", UseCase), name="valid_use_case"),
        CheckConstraint(one_of("status", ModelStatus), name="valid_status"),
        CheckConstraint("train_seconds IS NULL OR train_seconds >= 0", name="train_seconds"),
        Index("ix_model_versions_use_case_status", "use_case", "status"),
        # At most one selected model per use case, enforced by the database.
        Index(
            "uq_model_versions_one_selected",
            "use_case",
            unique=True,
            sqlite_where=text("status = 'selected'"),
            postgresql_where=text("status = 'selected'"),
        ),
    )

    use_case: Mapped[str] = mapped_column(String(40), nullable=False)
    model_name: Mapped[str] = mapped_column(String(60), nullable=False)  # e.g. "lstm"
    version: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. "20261116-1200"
    is_baseline: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ModelStatus.CANDIDATE, server_default="candidate", nullable=False
    )
    # Which data it learned from, e.g. "full-seed20261111-2026-11-10".
    dataset_version: Mapped[str] = mapped_column(String(80), nullable=False)
    features: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Relative to ml/ (e.g. "artifacts/demand_forecasting/lstm/20261116-1200.keras");
    # NULL for baselines, which are formulas without a saved model.
    artifact_path: Mapped[str | None] = mapped_column(String(255))
    trained_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    train_seconds: Mapped[float | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)

    metrics: Mapped[list["ModelMetric"]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan", lazy="selectin"
    )

    def metric(self, name: str, split: str = MetricSplit.TEST) -> float | None:
        for metric in self.metrics:
            if metric.name == name and metric.split == split:
                return metric.value
        return None

    def __repr__(self) -> str:
        return f"<ModelVersion {self.use_case}/{self.model_name} {self.version} {self.status}>"


class ModelMetric(IdMixin, Base):
    __tablename__ = "model_metrics"
    __table_args__ = (
        UniqueConstraint("model_version_id", "split", "name"),
        CheckConstraint(one_of("split", MetricSplit), name="valid_split"),
    )

    model_version_id: Mapped[int] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. "wape", "pr_auc"
    value: Mapped[float] = mapped_column(nullable=False)

    model_version: Mapped[ModelVersion] = relationship(back_populates="metrics")

    def __repr__(self) -> str:
        return f"<ModelMetric {self.split} {self.name}={self.value}>"
