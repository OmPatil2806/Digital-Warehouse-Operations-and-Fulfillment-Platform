"""Read the stored ML predictions and record managers' decisions on recommendations.

Predictions are written by the offline scoring step (scripts/score_models.py); every
scoring run adds rows with its own `scored_at`. The application shows the **latest run**
of each use case: the one with the latest `as_of`, the newest of those (a backtest made
as of an earlier day never replaces the current predictions). Decisions (approve /
reject) are made on the rows themselves and audited.

Runs made before the last day with orders can be checked against what happened next
(`check`): forecasts against the units then ordered, delay risks against when the
parcels then arrived.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, func, select
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
from app.models.order import Order, OrderItem
from app.models.shipment import Shipment
from app.models.user import User
from app.models.warehouse import Bin, Warehouse
from app.schemas import ml as schemas
from app.services.audit_service import AuditService

FORECAST_TOTALS = (7, 14, 30)
RISK_LEVELS = ("high", "medium", "low")


def _ratio(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


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
        """`scored_at` of the current run: the latest `as_of`, the newest of those."""
        return self.db.scalar(
            select(table.scored_at).order_by(table.as_of.desc(), table.scored_at.desc()).limit(1)
        )

    def _checkable_run(self, table: type, until: date) -> datetime | None:
        """The newest run made before `until`, so some of the days it predicts passed."""
        return self.db.scalar(
            select(table.scored_at)
            .where(table.as_of < until)
            .order_by(table.as_of.desc(), table.scored_at.desc())
            .limit(1)
        )

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
        """Headline numbers of the latest predictions for the dashboard (sums in the
        database: the latest run has tens of thousands of rows)."""
        pending_r, pending_s = (
            ReorderRecommendation.status == DecisionStatus.PENDING,
            SlottingRecommendation.status == DecisionStatus.PENDING,
        )
        stockouts_pending, stockouts_high = self._sums(
            ReorderRecommendation,
            func.count(),
            func.sum(case((ReorderRecommendation.priority == "high", 1), else_=0)),
            where=pending_r,
        )
        on_the_way, high_risk, at_risk = self._sums(
            DelayPrediction,
            func.count(),
            func.sum(case((DelayPrediction.risk_level == "high", 1), else_=0)),
            func.sum(case((DelayPrediction.risk_level != "low", 1), else_=0)),
        )
        saving = (
            SlottingRecommendation.current_seconds_per_day
            - SlottingRecommendation.recommended_seconds_per_day
        )
        slotting_pending, seconds_saved = self._sums(
            SlottingRecommendation,
            func.count(),
            func.sum(func.coalesce(saving, 0)),
            where=pending_s,
        )
        totals = dict.fromkeys((7, 30), 0.0)
        newest = self.latest_run(DemandForecast)
        if newest is not None:
            first = self.db.scalar(
                select(func.min(DemandForecast.day)).where(DemandForecast.scored_at == newest)
            )
            for days in totals:
                totals[days] = self.db.scalar(
                    select(func.coalesce(func.sum(DemandForecast.expected_units), 0.0)).where(
                        DemandForecast.scored_at == newest,
                        DemandForecast.day < first + timedelta(days=days),
                    )
                )
        as_of = [
            info.as_of
            for info in (
                self._scoring(t) for t in (ReorderRecommendation, DelayPrediction, DemandForecast)
            )
            if info is not None
        ]
        until = self.data_until()
        error, error_days = self.forecast_error(until) if until else (None, 0)
        return schemas.MLSummary(
            as_of=max(as_of) if as_of else None,
            stockouts_high=stockouts_high,
            stockouts_pending=stockouts_pending,
            orders_high_risk=high_risk,
            orders_at_risk=at_risk,
            orders_on_the_way=on_the_way,
            forecast_units_7_days=totals[7],
            forecast_units_30_days=totals[30],
            slotting_pending=slotting_pending,
            slotting_seconds_saved_per_day=seconds_saved,
            forecast_error=error,
            forecast_error_days=error_days,
        )

    def _sums(self, table: type, *columns: Any, where: Any = None) -> list:
        """Aggregates over the current run of a table (zeros when nothing is scored)."""
        newest = self.latest_run(table)
        if newest is None:
            return [0] * len(columns)
        query = select(*columns).where(table.scored_at == newest)
        if where is not None:
            query = query.where(where)
        return [value or 0 for value in self.db.execute(query).one()]

    # ------------------------------------------------- predictions vs reality
    def data_until(self) -> date | None:
        """The last day with orders: outcomes are known up to it."""
        newest = self.db.scalar(select(func.max(Order.created_at)))
        return None if newest is None else newest.astimezone(UTC).date()

    def check(self) -> schemas.PredictionCheck:
        until = self.data_until()
        if until is None:
            return schemas.PredictionCheck(data_until=None, demand=None, delay=None)
        return schemas.PredictionCheck(
            data_until=until, demand=self.demand_check(until), delay=self.delay_check(until)
        )

    def _model(self, version_id: int) -> ModelVersion | None:
        return self.db.get(ModelVersion, version_id)

    def _passed_days(self, scored_at: datetime, until: date) -> tuple[date, date]:
        """The first and last forecast day of a run that have passed by `until`."""
        first, last = self.db.execute(
            select(func.min(DemandForecast.day), func.max(DemandForecast.day)).where(
                DemandForecast.scored_at == scored_at, DemandForecast.day <= until
            )
        ).one()
        return first, last

    def _ordered(self, first: date, last: date, *columns: Any):
        """Order lines of the orders placed from `first` to `last` (the orders are found
        first: grouping a join of all order lines is slow on a large history)."""
        orders = select(Order.id).where(
            Order.created_at >= _day_start(first),
            Order.created_at < _day_start(last + timedelta(days=1)),
        )
        return (
            select(*columns)
            .join(Order, Order.id == OrderItem.order_id)
            .where(OrderItem.order_id.in_(orders))
        )

    def forecast_error(self, until: date) -> tuple[float | None, int]:
        """The period error of the latest checkable forecast and the days it covers
        (the dashboard's "forecast error"; the same as `demand_check().period_error`)."""
        scored_at = self._checkable_run(DemandForecast, until)
        if scored_at is None:
            return None, 0
        first, last = self._passed_days(scored_at, until)
        forecast = self.db.execute(
            select(DemandForecast.product_id, func.sum(DemandForecast.expected_units))
            .where(DemandForecast.scored_at == scored_at, DemandForecast.day <= until)
            .group_by(DemandForecast.product_id)
        ).all()
        actual = dict(
            self.db.execute(
                self._ordered(
                    first, last, OrderItem.product_id, func.sum(OrderItem.quantity)
                ).group_by(OrderItem.product_id)
            ).all()
        )
        wrong = sum(abs((actual.get(p) or 0) - units) for p, units in forecast)
        ordered = sum((actual.get(p) or 0) for p, _ in forecast)
        return _ratio(wrong, ordered), (last - first).days + 1

    def demand_check(self, until: date) -> schemas.DemandAccuracy | None:
        """The latest checkable forecast against the units ordered on its passed days."""
        scored_at = self._checkable_run(DemandForecast, until)
        if scored_at is None:
            return None
        rows = self.db.execute(
            select(
                DemandForecast.product_id,
                DemandForecast.day,
                DemandForecast.expected_units,
                DemandForecast.low_units,
                DemandForecast.high_units,
                DemandForecast.as_of,
                DemandForecast.model_version_id,
            ).where(DemandForecast.scored_at == scored_at)
        ).all()
        as_of, version_id = rows[0].as_of, rows[0].model_version_id
        days_forecast = len({r.day for r in rows})
        # Plain tuples (product, day, expected, low, high): much faster to loop over than
        # named rows for the tens of thousands of product-days of a full forecast.
        rows = [tuple(r[:5]) for r in rows if r.day <= until]
        first_day, last_day = self._passed_days(scored_at, until)
        # Units ordered per product and day, added up by the database (order times are
        # stored in UTC, so the stored date is the UTC day, as in the forecasts).
        order_day = func.date(Order.created_at)
        actual: dict[tuple[int, date], float] = {
            (product_id, date.fromisoformat(day)): float(units)
            for product_id, day, units in self.db.execute(
                self._ordered(
                    first_day,
                    last_day,
                    OrderItem.product_id,
                    order_day,
                    func.sum(OrderItem.quantity),
                ).group_by(OrderItem.product_id, order_day)
            )
        }

        daily_forecast: dict[date, float] = defaultdict(float)
        daily_actual: dict[date, float] = defaultdict(float)
        product_forecast: dict[int, float] = defaultdict(float)
        product_actual: dict[int, float] = defaultdict(float)
        abs_error = inside = 0.0
        for product_id, day, expected, low, high in rows:
            units = actual.get((product_id, day), 0.0)
            abs_error += abs(units - expected)
            inside += low <= units <= high
            daily_forecast[day] += expected
            daily_actual[day] += units
            product_forecast[product_id] += expected
            product_actual[product_id] += units
        forecast_units, actual_units = sum(daily_forecast.values()), sum(daily_actual.values())
        period_abs = sum(abs(product_actual[p] - f) for p, f in product_forecast.items())
        days_checked = (last_day - first_day).days + 1
        model = self._model(version_id)
        test_error = None
        if model is not None:
            for span in (30, 14, 7):
                if span <= days_checked:
                    test_error = model.metric(f"wape_{span}d_total", MetricSplit.TEST)
                    break
        return schemas.DemandAccuracy(
            model_name=model.model_name if model else "unknown",
            is_baseline=bool(model and model.is_baseline),
            scored_at=scored_at,
            as_of=as_of,
            first_day=first_day,
            last_day=last_day,
            days_checked=days_checked,
            days_forecast=days_forecast,
            products=len(product_forecast),
            forecast_units=forecast_units,
            actual_units=actual_units,
            daily_error=_ratio(abs_error, actual_units),
            period_error=_ratio(period_abs, actual_units),
            bias=_ratio(forecast_units - actual_units, actual_units),
            range_coverage=_ratio(inside, len(rows)),
            test_error=None if test_error is None else float(test_error),
            daily=[
                schemas.AccuracyDay(
                    day=day, forecast_units=daily_forecast[day], actual_units=daily_actual[day]
                )
                for day in sorted(daily_forecast)
            ],
        )

    def delay_check(self, until: date) -> schemas.DelayAccuracy | None:
        """The latest checkable delay run against when its parcels were delivered."""
        scored_at = self._checkable_run(DelayPrediction, until)
        if scored_at is None:
            return None
        rows = self.db.execute(
            select(
                DelayPrediction.risk_level,
                DelayPrediction.as_of,
                DelayPrediction.model_version_id,
                Shipment.delivered_at,
                Shipment.expected_delivery_date,
            )
            .join(Shipment, Shipment.id == DelayPrediction.shipment_id)
            .where(DelayPrediction.scored_at == scored_at)
        ).all()
        if not rows:
            return None
        counts = {level: {"parcels": 0, "delivered": 0, "late": 0} for level in RISK_LEVELS}
        for r in rows:
            level = counts[r.risk_level]
            level["parcels"] += 1
            if r.delivered_at is not None:
                level["delivered"] += 1
                level["late"] += r.delivered_at.astimezone(UTC).date() > r.expected_delivery_date
        delivered = sum(c["delivered"] for c in counts.values())
        late = sum(c["late"] for c in counts.values())
        model = self._model(rows[0].model_version_id)
        return schemas.DelayAccuracy(
            model_name=model.model_name if model else "unknown",
            is_baseline=bool(model and model.is_baseline),
            scored_at=scored_at,
            as_of=rows[0].as_of,
            parcels=len(rows),
            delivered=delivered,
            on_the_way=len(rows) - delivered,
            late=late,
            late_rate=_ratio(late, delivered),
            late_flagged=_ratio(counts["high"]["late"] + counts["medium"]["late"], late),
            levels=[
                schemas.DelayLevelCheck(
                    risk_level=level,
                    **c,
                    late_rate=_ratio(c["late"], c["delivered"]),
                )
                for level, c in counts.items()
            ],
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
