"""Score every use case with its selected model and store the predictions.

    for each use case: selected model (registry) -> predictor -> rows -> prediction table

Each run adds rows with the same `scored_at`; nothing is overwritten, so predictions can
later be compared with what happened. Use cases without a selected model are skipped.

A **backtest** (`as_of` earlier than the last day of data) scores the use cases whose
outcome can be checked, demand forecasts and delivery delays, as if it were that day:
later days are hidden from the predictors. The days after it then show how the
predictions did. Both selected models were trained on the days before their test period
(the last 90 days), so a backtest inside that period checks them on days they never saw.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import Engine, insert
from sqlalchemy.orm import Session

from app.models.ml import ModelVersion
from app.models.ml_results import RESULT_TABLES
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from inference import (
    delay_predictor,
    demand_predictor,
    movement_predictor,
    recommendation_predictor,
    reorder_predictor,
    slotting_predictor,
)
from inference.common import Context
from registry.register_model import selected_model
from training.data import history_range, open_dataset
from training.use_cases import USE_CASES

PREDICTORS: dict[str, Callable[[Engine, Context], list[dict]]] = {
    "demand_forecasting": demand_predictor.predict,
    "reorder": reorder_predictor.predict,
    "movement_classification": movement_predictor.predict,
    "slotting": slotting_predictor.predict,
    "delay_prediction": delay_predictor.predict,
    "recommendation": recommendation_predictor.predict,
}
BATCH = 10_000
BACKTEST_USE_CASES = ("demand_forecasting", "delay_prediction")  # outcomes are checkable


@dataclass
class Scored:
    use_case: str
    model_name: str | None  # None: no selected model, skipped
    rows: int
    seconds: float


def store(
    engine: Engine, use_case: str, model: ModelVersion, rows: list[dict], scored_at: datetime, as_of
) -> int:
    table = RESULT_TABLES[use_case].__table__
    common = {"model_version_id": model.id, "scored_at": scored_at, "as_of": as_of}
    with engine.begin() as connection:
        for start in range(0, len(rows), BATCH):
            connection.execute(
                insert(table), [{**row, **common} for row in rows[start : start + BATCH]]
            )
    return len(rows)


def score(
    database: Path = DEFAULT_DATABASE,
    *,
    use_cases: Sequence[str] | None = None,
    report: Callable[[str], None] = print,
    models: dict[str, ModelVersion] | None = None,
    as_of: date | None = None,
) -> list[Scored]:
    """Score the chosen use cases (default all) with their selected models; `models`
    overrides the model of a use case (tests and comparisons). With `as_of` before the
    last day of data: a backtest of the checkable use cases (default both)."""
    engine = open_dataset(database)
    upgrade_database(database)
    first, last = history_range(engine)
    backtest = as_of is not None and as_of < last
    if as_of is not None:
        if not first < as_of <= last:
            engine.dispose()
            raise ValueError(f"as_of must be after {first} and on or before {last}")
        unsupported = set(use_cases or ()) - set(BACKTEST_USE_CASES)
        if backtest and unsupported:
            engine.dispose()
            raise ValueError(
                f"only {', '.join(BACKTEST_USE_CASES)} can be backtested, "
                f"not {', '.join(sorted(unsupported))}"
            )
        if backtest and use_cases is None:
            use_cases = BACKTEST_USE_CASES
        last = as_of
    scored_at = datetime.now(UTC)
    chosen = [u for u in USE_CASES if use_cases is None or u.name in use_cases]
    results = []
    for info in chosen:
        started = time.perf_counter()
        model = (models or {}).get(info.name) or selected_model(engine, info.name)
        if model is None:
            report(f"  {info.title:<26} skipped: no selected model (train it first)")
            results.append(Scored(info.name, None, 0, 0.0))
            continue
        rows = PREDICTORS[info.name](engine, Context(model, first, last, backtest=backtest))
        count = store(engine, info.name, model, rows, scored_at, last)
        seconds = time.perf_counter() - started
        report(f"  {info.title:<26} {model.model_name:<28} {count:>8,} rows  {seconds:>5.0f} s")
        results.append(Scored(info.name, model.model_name, count, seconds))
    engine.dispose()
    return results


def latest_rows(engine: Engine, use_case: str) -> list:
    """The rows of the latest scoring run of a use case (helper for checks and tests):
    the run with the latest `as_of`, the newest of those (as the application shows)."""
    table = RESULT_TABLES[use_case]
    with Session(engine) as session:
        newest = (
            session.query(table.scored_at)
            .order_by(table.as_of.desc(), table.scored_at.desc())
            .first()
        )
        if newest is None:
            return []
        return session.query(table).filter(table.scored_at == newest[0]).all()
