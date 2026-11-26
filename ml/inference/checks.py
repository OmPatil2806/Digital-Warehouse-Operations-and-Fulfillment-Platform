"""Checks of the selected models and of their latest stored predictions.

The database already refuses impossible values (probabilities outside 0..1, a low
forecast above the expected one, unknown classes). These checks cover what it cannot:

- **model load**: every selected network loads from its saved file (with its custom
  layers) and gives finite outputs of the expected shape for a small input;
- **shape**: each prediction table has the rows it should (every product, every
  forecast day, every shipment still on its way, ranks 1..k without gaps);
- **values**: no infinite numbers (SQLite stores them), forecasts for the days right
  after `as_of`, slotting moves that really save time.

Run after scoring (scripts/check_models.py); CI fails when a check fails.
"""

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

import keras
import numpy as np
from sqlalchemy import Engine

from app.models.ml import ModelVersion
from inference.common import Context
from inference.score import latest_rows
from registry.register_model import selected_model
from training.data import history_range, read_frame
from training.use_cases import USE_CASES


@dataclass
class CheckResult:
    use_case: str
    model_name: str | None  # None: no selected model
    rows: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.model_name is not None and not self.problems


def _finite(rows: list, *fields: str) -> list[str]:
    bad = [
        f"{name}={getattr(r, name)!r} (id {r.id})"
        for r in rows
        for name in fields
        if getattr(r, name) is not None and not math.isfinite(getattr(r, name))
    ]
    return [f"not a finite number: {', '.join(bad[:3])}"] if bad else []


def check_model_loads(model: ModelVersion, ctx: Context) -> list[str]:
    """A selected network loads and predicts finite numbers of the right shape."""
    if model.is_baseline:
        return []  # baselines are rules, refitted when scoring: nothing saved to load
    try:
        network = ctx.keras_model()
    except Exception as exc:  # any failure to load is the finding
        return [f"model file does not load: {type(exc).__name__}: {exc}"]
    # Two all-zero examples in the model's own input structure (a dict of named inputs
    # or a single tensor); variable lengths become 1.
    sample = keras.tree.map_structure(
        lambda tensor: np.zeros((2, *(d or 1 for d in tensor.shape[1:])), dtype="float32"),
        network.input,
    )
    try:
        outputs = network.predict(sample, verbose=0)
    except Exception as exc:  # a model that cannot predict is the finding
        return [f"the model cannot predict: {type(exc).__name__}: {str(exc)[:200]}"]
    outputs = outputs if isinstance(outputs, list) else [outputs]
    problems = []
    for output, tensor in zip(outputs, network.outputs, strict=True):
        array = np.asarray(output)
        expected = (2, *(d or array.shape[i + 1] for i, d in enumerate(tensor.shape[1:])))
        if array.shape != expected:
            problems.append(f"output shape {array.shape}, expected {expected}")
        if not np.isfinite(array).all():
            problems.append("the model outputs NaN or infinite numbers")
    return problems


# -------------------------------------------------------------- per use case
def _demand(engine: Engine, rows: list, ctx: Context) -> list[str]:
    horizon = int(ctx.params.get("horizon", 30))
    products = int(read_frame(engine, "SELECT COUNT(*) AS n FROM products").n[0])
    problems = _finite(rows, "expected_units", "low_units", "high_units")
    days_of: dict[int, set] = defaultdict(set)
    for r in rows:
        days_of[r.product_id].add(r.day)
    if len(days_of) != products:
        problems.append(f"forecasts for {len(days_of)} of {products} products")
    as_of = rows[0].as_of
    wanted = {as_of + timedelta(days=d) for d in range(1, horizon + 1)}
    gaps = [p for p, days in days_of.items() if days != wanted]
    if gaps:
        problems.append(f"{len(gaps)} product(s) without exactly the {horizon} days after {as_of}")
    return problems


def _reorder(engine: Engine, rows: list, ctx: Context) -> list[str]:
    problems = _finite(rows, "probability")
    if any(r.reorder_date < r.as_of for r in rows):
        problems.append("a reorder date before the day of the prediction")
    pairs = [(r.product_id, r.warehouse_id) for r in rows]
    if len(pairs) != len(set(pairs)):
        problems.append("more than one recommendation for a product in a warehouse")
    return problems


def _movement(engine: Engine, rows: list, ctx: Context) -> list[str]:
    products = int(read_frame(engine, "SELECT COUNT(*) AS n FROM products").n[0])
    problems = _finite(rows, "picks_per_day")
    if len({r.product_id for r in rows}) != products or len(rows) != products:
        problems.append(f"{len(rows)} classes for {products} products (one each expected)")
    if any(r.picks_per_day < 0 for r in rows):
        problems.append("negative picks per day")
    return problems


def _slotting(engine: Engine, rows: list, ctx: Context) -> list[str]:
    problems = _finite(rows, "current_seconds_per_day", "recommended_seconds_per_day")
    if any(r.current_bin_id == r.recommended_bin_id for r in rows):
        problems.append("a move to the bin the product is already in")
    if any(
        r.current_seconds_per_day is not None
        and r.recommended_seconds_per_day >= r.current_seconds_per_day
        for r in rows
    ):
        problems.append("a move that does not save picking time")
    return problems


def _delay(engine: Engine, rows: list, ctx: Context) -> list[str]:
    problems = _finite(rows, "probability")
    if rows[0].as_of == ctx.last:  # the current run: every parcel on its way has a risk
        on_the_way = set(
            read_frame(engine, "SELECT order_id FROM shipments WHERE delivered_at IS NULL").order_id
        )
        predicted = {r.order_id for r in rows}
        if predicted != on_the_way:
            problems.append(
                f"risks for {len(predicted)} parcels, {len(on_the_way)} are on their way"
            )
    return problems


def _recommendation(engine: Engine, rows: list, ctx: Context) -> list[str]:
    problems = _finite(rows, "score")
    ranks: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        ranks[r.product_id].append(r.rank)
    if any(sorted(found) != list(range(1, len(found) + 1)) for found in ranks.values()):
        problems.append("ranks with gaps or repeats")
    pairs = [(r.product_id, r.recommended_product_id) for r in rows]
    if len(pairs) != len(set(pairs)):
        problems.append("the same product recommended twice")
    return problems


CHECKS: dict[str, Callable[[Engine, list, Context], list[str]]] = {
    "demand_forecasting": _demand,
    "reorder": _reorder,
    "movement_classification": _movement,
    "slotting": _slotting,
    "delay_prediction": _delay,
    "recommendation": _recommendation,
}
# Empty is fine for these: there may be no product at risk, no better bin, or no
# parcel on its way.
MAY_BE_EMPTY = {"reorder", "slotting", "delay_prediction"}


def check(engine: Engine, use_cases: list[str] | None = None) -> list[CheckResult]:
    first, last = history_range(engine)
    results = []
    for info in USE_CASES:
        if use_cases is not None and info.name not in use_cases:
            continue
        model = selected_model(engine, info.name)
        if model is None:
            results.append(CheckResult(info.name, None, problems=["no selected model"]))
            continue
        ctx = Context(model, first, last)
        result = CheckResult(info.name, model.model_name)
        result.problems += check_model_loads(model, ctx)
        rows = [r for r in latest_rows(engine, info.name) if r.model_version_id == model.id]
        result.rows = len(rows)
        if not rows:
            if info.name not in MAY_BE_EMPTY:
                result.problems.append(
                    "no predictions from the selected model (run scripts/score_models.py)"
                )
        else:
            result.problems += CHECKS[info.name](engine, rows, ctx)
        results.append(result)
    return results
