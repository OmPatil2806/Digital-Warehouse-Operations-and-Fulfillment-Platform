"""Read the stored ML predictions and record managers' decisions on recommendations.

Predictions are written by the offline scoring step (scripts/score_models.py); every
scoring run adds rows with its own `scored_at`. The application shows the **latest run**
of each use case. Decisions (approve / reject) are made on the rows themselves and
audited.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Product, SupplierProduct
from app.models.ml import MetricSplit, ModelStatus, ModelVersion, UseCase
from app.models.ml_results import (
    RESULT_TABLES,
    DecisionStatus,
    DelayPrediction,
    DemandForecast,
    MovementClassification,
    ProductRecommendation,
    ReorderRecommendation,
    SlottingRecommendation,
)
from app.models.order import Order
from app.models.user import User
from app.models.warehouse import Bin, Warehouse
from app.schemas import ml as schemas
from app.services.audit_service import AuditService

FORECAST_TOTALS = (7, 14, 30)


def _product(product: Product) -> schemas.ProductRef:
    return schemas.ProductRef(id=product.id, sku=product.sku, name=product.name)


def _bin(bin_: Bin | None) -> schemas.BinRef | None:
    if bin_ is None:
        return None
    rack = bin_.shelf.rack
    return schemas.BinRef(
        id=bin_.id,
        location_code=bin_.location_code,
        zone_type=rack.zone.zone_type,
        level=bin_.shelf.level,
        distance_to_packing_m=float(rack.distance_to_packing_m),
    )


class MLService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------- runs
    def latest_run(self, table: type) -> datetime | None:
        return self.db.scalar(select(func.max(table.scored_at)))

    def _scoring(self, table: type) -> schemas.ScoringInfo | None:
        """Which model made the latest run of a table, when, and for which day."""
        newest = self.latest_run(table)
        if newest is None:
            return None
        row = self.db.scalars(select(table).where(table.scored_at == newest).limit(1)).first()
        model = self.db.get(ModelVersion, row.model_version_id)
        return schemas.ScoringInfo(
            model_name=model.model_name if model else "unknown",
            is_baseline=bool(model and model.is_baseline),
            scored_at=row.scored_at,
            as_of=row.as_of,
        )

    def models(self) -> list[schemas.ModelSummary]:
        """The selected model of every use case, with its test metrics and latest run."""
        out = []
        for use_case in UseCase:
            model = self.db.scalars(
                select(ModelVersion).where(
                    ModelVersion.use_case == use_case,
                    ModelVersion.status == ModelStatus.SELECTED,
                )
            ).one_or_none()
            if model is None:
                continue
            table = RESULT_TABLES[use_case.value]
            newest = self.latest_run(table)
            count, as_of = 0, None
            if newest is not None:
                count = self.db.scalar(
                    select(func.count()).select_from(table).where(table.scored_at == newest)
                )
                as_of = self.db.scalar(select(table.as_of).where(table.scored_at == newest))
            out.append(
                schemas.ModelSummary(
                    use_case=use_case.value,
                    model_name=model.model_name,
                    version=model.version,
                    is_baseline=model.is_baseline,
                    dataset_version=model.dataset_version,
                    trained_at=model.trained_at,
                    test_metrics={
                        m.name: m.value for m in model.metrics if m.split == MetricSplit.TEST
                    },
                    scored_at=newest,
                    as_of=as_of,
                    predictions=count or 0,
                )
            )
        return out

    # ----------------------------------------------------------------- demand
    def demand_forecast(self, product_id: int) -> schemas.DemandForecastResponse:
        product = self._get_product(product_id)
        newest = self.latest_run(DemandForecast)
        rows = []
        if newest is not None:
            rows = list(
                self.db.scalars(
                    select(DemandForecast)
                    .where(
                        DemandForecast.scored_at == newest,
                        DemandForecast.product_id == product_id,
                    )
                    .order_by(DemandForecast.day)
                )
            )
        days = [
            schemas.ForecastDay(
                day=r.day,
                expected_units=r.expected_units,
                low_units=r.low_units,
                high_units=r.high_units,
            )
            for r in rows
        ]
        totals = [
            schemas.ForecastTotal(
                days=n,
                expected_units=sum(d.expected_units for d in days[:n]),
                low_units=sum(d.low_units for d in days[:n]),
                high_units=sum(d.high_units for d in days[:n]),
            )
            for n in FORECAST_TOTALS
            if len(days) >= n
        ]
        return schemas.DemandForecastResponse(
            product=_product(product),
            scoring=self._scoring(DemandForecast) if rows else None,
            days=days,
            totals=totals,
        )

    # ---------------------------------------------------------------- reorder
    def reorder_recommendations(
        self,
        *,
        status: DecisionStatus | None = None,
        priority: str | None = None,
        warehouse_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[schemas.ReorderRecommendationResponse], int]:
        """Latest run, highest risk first."""
        query = self._latest(ReorderRecommendation)
        if query is None:
            return [], 0
        if status is not None:
            query = query.where(ReorderRecommendation.status == status)
        if priority is not None:
            query = query.where(ReorderRecommendation.priority == priority)
        if warehouse_id is not None:
            query = query.where(ReorderRecommendation.warehouse_id == warehouse_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(ReorderRecommendation.probability.desc(), ReorderRecommendation.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._reorder(r) for r in rows], total

    def _reorder(self, r: ReorderRecommendation) -> schemas.ReorderRecommendationResponse:
        warehouse = self.db.get(Warehouse, r.warehouse_id)
        return schemas.ReorderRecommendationResponse(
            id=r.id,
            product=_product(self.db.get(Product, r.product_id)),
            warehouse_id=r.warehouse_id,
            warehouse_code=warehouse.code if warehouse else "?",
            probability=r.probability,
            priority=r.priority,
            reorder_date=r.reorder_date,
            quantity=r.quantity,
            reasons=list(r.reasons or []),
            purchase_order_id=r.purchase_order_id,
            status=r.status,
            decided_by_id=r.decided_by_id,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
            scored_at=r.scored_at,
            as_of=r.as_of,
        )

    def decide_reorder(
        self, recommendation_id: int, *, approve: bool, user: User, note: str | None
    ) -> schemas.ReorderRecommendationResponse:
        """Approving drafts a purchase order (through the purchasing rules) and links it;
        rejecting only records the decision."""
        row = self.db.get(ReorderRecommendation, recommendation_id)
        if row is None:
            raise NotFoundError("Reorder recommendation not found")
        if row.status != DecisionStatus.PENDING:
            raise ConflictError(f"This recommendation is already {row.status}")
        if approve:
            row.purchase_order_id = self._draft_purchase_order(row, user).id
        self._decide(row, "ml.reorder", approve=approve, user=user, note=note)
        return self._reorder(row)

    def _draft_purchase_order(self, row: ReorderRecommendation, user: User):
        from app.schemas.purchase import PurchaseOrderCreate, PurchaseOrderLine
        from app.services.purchase_order_service import PurchaseOrderService

        product = self.db.get(Product, row.product_id)
        offers = list(
            self.db.scalars(select(SupplierProduct).where(SupplierProduct.product_id == product.id))
        )
        supplier_id = product.default_supplier_id
        if supplier_id is None:
            preferred = [o for o in offers if o.is_preferred] or offers
            supplier_id = preferred[0].supplier_id if preferred else None
        if supplier_id is None:
            raise UnprocessableError(
                f"{product.sku} has no supplier: set a default supplier before approving"
            )
        offer = next((o for o in offers if o.supplier_id == supplier_id), None)
        quantity = max(row.quantity, offer.min_order_qty if offer else 1, 1)
        return PurchaseOrderService(self.db).create(
            PurchaseOrderCreate(
                supplier_id=supplier_id,
                warehouse_id=row.warehouse_id,
                notes=(
                    f"From ML reorder recommendation #{row.id}: stockout risk "
                    f"{row.probability:.0%} within 14 days"
                ),
                items=[PurchaseOrderLine(product_id=product.id, quantity=quantity)],
            ),
            user=user,
        )

    # --------------------------------------------------------------- movement
    def movement(self, product_id: int) -> schemas.MovementResponse:
        product = self._get_product(product_id)
        query = self._latest(MovementClassification)
        row = (
            None
            if query is None
            else self.db.scalars(
                query.where(MovementClassification.product_id == product_id)
            ).first()
        )
        if row is None:
            raise NotFoundError("No movement class for this product yet")
        return self._movement(row, product)

    def _movement(self, row: MovementClassification, product: Product) -> schemas.MovementResponse:
        return schemas.MovementResponse(
            product=_product(product),
            movement_class=row.movement_class,
            picks_per_day=row.picks_per_day,
            scored_at=row.scored_at,
            as_of=row.as_of,
        )

    def movements(
        self, *, movement_class: str | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[schemas.MovementResponse], int]:
        """Latest run, most picked first."""
        query = self._latest(MovementClassification)
        if query is None:
            return [], 0
        if movement_class is not None:
            query = query.where(MovementClassification.movement_class == movement_class)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(MovementClassification.picks_per_day.desc(), MovementClassification.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._movement(r, self.db.get(Product, r.product_id)) for r in rows], total

    def movement_summary(self) -> schemas.MovementSummary:
        query = self._latest(MovementClassification)
        counts = {"fast": 0, "medium": 0, "slow": 0}
        picks = dict.fromkeys(counts, 0.0)
        if query is not None:
            for row in self.db.scalars(query):
                counts[row.movement_class] += 1
                picks[row.movement_class] += row.picks_per_day
        total = sum(picks.values())
        return schemas.MovementSummary(
            scoring=self._scoring(MovementClassification),
            counts=counts,
            pick_share={k: (v / total if total else 0.0) for k, v in picks.items()},
        )

    # --------------------------------------------------------------- slotting
    def slotting_recommendations(
        self,
        *,
        status: DecisionStatus | None = None,
        warehouse_id: int | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[schemas.SlottingRecommendationResponse], int]:
        """Latest run, biggest time saving first (new pick locations last)."""
        query = self._latest(SlottingRecommendation)
        if query is None:
            return [], 0
        if status is not None:
            query = query.where(SlottingRecommendation.status == status)
        if warehouse_id is not None:
            query = query.where(SlottingRecommendation.warehouse_id == warehouse_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        saving = SlottingRecommendation.current_seconds_per_day - (
            SlottingRecommendation.recommended_seconds_per_day
        )
        rows = self.db.scalars(
            query.order_by(saving.is_(None), saving.desc(), SlottingRecommendation.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._slotting(r) for r in rows], total

    def _slotting(self, r: SlottingRecommendation) -> schemas.SlottingRecommendationResponse:
        warehouse = self.db.get(Warehouse, r.warehouse_id)
        saved = (
            None
            if r.current_seconds_per_day is None
            else r.current_seconds_per_day - r.recommended_seconds_per_day
        )
        return schemas.SlottingRecommendationResponse(
            id=r.id,
            product=_product(self.db.get(Product, r.product_id)),
            warehouse_id=r.warehouse_id,
            warehouse_code=warehouse.code if warehouse else "?",
            current_bin=_bin(self.db.get(Bin, r.current_bin_id) if r.current_bin_id else None),
            recommended_bin=_bin(self.db.get(Bin, r.recommended_bin_id)),
            current_seconds_per_day=r.current_seconds_per_day,
            recommended_seconds_per_day=r.recommended_seconds_per_day,
            seconds_saved_per_day=saved,
            status=r.status,
            decided_by_id=r.decided_by_id,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
            scored_at=r.scored_at,
            as_of=r.as_of,
        )

    def decide_slotting(
        self, recommendation_id: int, *, approve: bool, user: User, note: str | None
    ) -> schemas.SlottingRecommendationResponse:
        row = self.db.get(SlottingRecommendation, recommendation_id)
        if row is None:
            raise NotFoundError("Slotting recommendation not found")
        self._decide(row, "ml.slotting", approve=approve, user=user, note=note)
        return self._slotting(row)

    # ------------------------------------------------------------------ delay
    def order_delay_risk(self, order_id: int) -> schemas.OrderDelayRisk:
        order = self.db.get(Order, order_id)
        if order is None:
            raise NotFoundError("Order not found")
        query = self._latest(DelayPrediction)
        row = (
            None
            if query is None
            else self.db.scalars(query.where(DelayPrediction.order_id == order_id)).first()
        )
        return schemas.OrderDelayRisk(
            order_id=order_id, prediction=self._delay(row, order) if row else None
        )

    def delay_risks(
        self, *, risk_level: str | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[schemas.DelayRiskResponse], int]:
        """Latest run, highest risk first."""
        query = self._latest(DelayPrediction)
        if query is None:
            return [], 0
        if risk_level is not None:
            query = query.where(DelayPrediction.risk_level == risk_level)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.db.scalars(
            query.order_by(DelayPrediction.probability.desc(), DelayPrediction.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._delay(r, self.db.get(Order, r.order_id)) for r in rows], total

    @staticmethod
    def _delay(row: DelayPrediction, order: Order) -> schemas.DelayRiskResponse:
        return schemas.DelayRiskResponse(
            order_id=row.order_id,
            order_number=order.order_number,
            shipment_id=row.shipment_id,
            probability=row.probability,
            risk_level=row.risk_level,
            reasons=list(row.reasons or []),
            scored_at=row.scored_at,
            as_of=row.as_of,
        )

    # --------------------------------------------------------- recommendations
    def product_recommendations(
        self, product_id: int, *, active_only: bool = False
    ) -> schemas.ProductRecommendationsResponse:
        product = self._get_product(product_id)
        query = self._latest(ProductRecommendation)
        rows = (
            []
            if query is None
            else list(
                self.db.scalars(
                    query.where(ProductRecommendation.product_id == product_id).order_by(
                        ProductRecommendation.rank
                    )
                )
            )
        )
        items = []
        for row in rows:
            other = self.db.get(Product, row.recommended_product_id)
            if other is None or (active_only and not other.is_active):
                continue
            items.append(
                schemas.RecommendedProduct(rank=row.rank, product=_product(other), score=row.score)
            )
        return schemas.ProductRecommendationsResponse(
            product=_product(product),
            scoring=self._scoring(ProductRecommendation) if rows else None,
            items=items,
        )

    # ---------------------------------------------------------------- summary
    def summary(self) -> schemas.MLSummary:
        """Headline numbers of the latest predictions for the dashboard."""
        reorder = self._latest(ReorderRecommendation)
        pending = (
            []
            if reorder is None
            else list(
                self.db.scalars(
                    reorder.where(ReorderRecommendation.status == DecisionStatus.PENDING)
                )
            )
        )
        delays = self._latest(DelayPrediction)
        risky = [] if delays is None else list(self.db.scalars(delays))
        slotting = self._latest(SlottingRecommendation)
        moves = (
            []
            if slotting is None
            else list(
                self.db.scalars(
                    slotting.where(SlottingRecommendation.status == DecisionStatus.PENDING)
                )
            )
        )
        forecast = self._latest(DemandForecast)
        totals = {7: 0.0, 30: 0.0}
        if forecast is not None:
            rows = list(self.db.scalars(forecast))
            if rows:
                first = min(r.day for r in rows)
                for days in totals:
                    totals[days] = sum(
                        r.expected_units for r in rows if (r.day - first).days < days
                    )
        as_of = [
            info.as_of
            for info in (
                self._scoring(t) for t in (ReorderRecommendation, DelayPrediction, DemandForecast)
            )
            if info is not None
        ]
        return schemas.MLSummary(
            as_of=max(as_of) if as_of else None,
            stockouts_high=sum(r.priority == "high" for r in pending),
            stockouts_pending=len(pending),
            orders_high_risk=sum(r.risk_level == "high" for r in risky),
            orders_at_risk=sum(r.risk_level != "low" for r in risky),
            orders_on_the_way=len(risky),
            forecast_units_7_days=totals[7],
            forecast_units_30_days=totals[30],
            slotting_pending=len(moves),
            slotting_seconds_saved_per_day=sum(
                (r.current_seconds_per_day or 0) - r.recommended_seconds_per_day
                for r in moves
                if r.current_seconds_per_day is not None
            ),
        )

    # ---------------------------------------------------------------- helpers
    def _latest(self, table: type):
        newest = self.latest_run(table)
        return None if newest is None else select(table).where(table.scored_at == newest)

    def _get_product(self, product_id: int) -> Product:
        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError("Product not found")
        return product

    def _decide(
        self, row: Any, action: str, *, approve: bool, user: User, note: str | None
    ) -> None:
        if row.status != DecisionStatus.PENDING:
            raise ConflictError(f"This recommendation is already {row.status}")
        row.status = DecisionStatus.APPROVED if approve else DecisionStatus.REJECTED
        row.decided_by_id = user.id
        row.decided_at = datetime.now(UTC)
        row.decision_note = note
        AuditService(self.db).record(
            f"{action}.{'approve' if approve else 'reject'}",
            row.__tablename__,
            row.id,
            summary=f"{'Approved' if approve else 'Rejected'} for product {row.product_id}",
            changes={"status": {"old": DecisionStatus.PENDING.value, "new": row.status}},
            actor=user,
        )
        self.db.commit()
