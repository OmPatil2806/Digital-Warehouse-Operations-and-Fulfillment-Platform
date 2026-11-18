"""Train and compare slotting methods (use case 4): which bin should each product be
picked from?

The suitability networks (configs/slotting.yaml) learn, from (product, bin) pairs on the
training period, how many seconds of picking per day a product will cost in a bin over
the next weeks: its coming picks (from its recent picks, trend and last year's season)
times the estimated pick time of that bin (walking distance, units per pick, shelf
height for heavy goods). The shared optimizer turns the scores into a layout that
respects every hard rule. ABC slotting (fast movers nearest) is the baseline.

Each layout is planned on the last day of a period and judged on the period after it
with the real picks, against where the products actually were (the current layout):

- `pick_time_reduction` (selection, higher is better) and `distance_reduction`
  (pick-weighted walking distance) versus the current layout;
- `violations`: zone, weight, volume and unplaced products, which must be 0 (a layout
  with violations scores -1);
- `bins_used_share`, `mean_volume_fill`: utilisation; `moved_share`: products that move.

Run from ml/:  python -m training.train_slotting [--database PATH]
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from baselines.slotting import abc_cost
from data_generation.database import DEFAULT_DATABASE, upgrade_database
from evaluation import metrics
from feature_engineering.slotting_features import (
    BIN_NUMERIC,
    PRODUCT_NUMERIC,
    Layout,
    current_slots,
    face_need,
    load_layout,
    load_picks,
    pair_features,
    pick_seconds,
    product_state,
)
from models.slotting.optimizer import Assignment, CostFunction, assign, violations
from registry.register_model import Selection
from training import keras_setup
from training.config import ExperimentConfig, load_config
from training.data import dataset_version, history_range, open_dataset
from training.experiment import ModelResult, Reporter, register_results, timer
from training.splits import chronological_split

USE_CASE = "slotting"
SELECTION_METRIC = "selection_score"  # = pick_time_reduction when there are no violations
REPORT = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / f"{USE_CASE}.md"
FEATURES = [*PRODUCT_NUMERIC, *BIN_NUMERIC, "category", "zone", "speed_x_distance", "heavy_x_level"]
HISTORY_DAYS = 90


@dataclass
class SlottingRun:
    version: str
    dataset_version: str
    split_description: str
    training_pairs: int
    current: dict[str, dict[str, float]]
    oracle: dict[str, dict[str, float]]
    results: list[ModelResult]
    selection: Selection


class Data:
    """Everything a slotting experiment needs from the database."""

    def __init__(self, engine, first, last) -> None:
        self.engine, self.first = engine, first
        self.layout: Layout = load_layout(engine)
        self.days = (last - first).days + 1
        self.lines, self.units = load_picks(engine, self.layout, first, self.days)

    def products(self, warehouse: int, day: int) -> np.ndarray:
        """Products picked in the warehouse during the 90 days up to `day`: need a face."""
        picked = self.lines[warehouse, :, day - HISTORY_DAYS + 1 : day + 1].sum(axis=1)
        return np.flatnonzero(picked > 0)

    def period(self, warehouse: int, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
        """Real picks per day and units per pick per product in days start..end."""
        lines = self.lines[warehouse, :, start : end + 1]
        units = self.units[warehouse, :, start : end + 1]
        per_pick = np.where(lines.sum(1) > 0, units.sum(1) / np.maximum(lines.sum(1), 1), 1.0)
        return lines.mean(axis=1), per_pick


def training_pairs(
    data: Data, days: list[int], horizon: int, bins_per_product: int, seed: int
) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Random allowed bins for each product with demand, labelled log(1 + seconds/day) of
    the next `horizon` days."""
    rng = np.random.default_rng(seed)
    layout, parts, labels = data.layout, [], []
    for day in days:
        state = product_state(data.lines, data.units, day)
        for w, warehouse_id in enumerate(layout.warehouse_ids):
            in_wh = layout.bin_warehouse == warehouse_id
            products = data.products(w, day)
            if not len(products):
                continue
            future, _ = data.period(w, day + 1, day + horizon)
            p_rows, b_rows = [], []
            for p in products:
                options = np.flatnonzero(layout.allowed(p) & in_wh)
                if len(options):
                    picked = rng.choice(options, min(bins_per_product, len(options)), False)
                    p_rows.extend([p] * len(picked))
                    b_rows.extend(picked)
            p_arr, b_arr = np.array(p_rows), np.array(b_rows)
            parts.append(pair_features(layout, state, w, p_arr, b_arr))
            seconds = pick_seconds(layout, p_arr, b_arr, state.units_per_pick[w, p_arr])
            labels.append(np.log1p(future[p_arr] * seconds))
    if not parts:
        raise ValueError("no training pairs: the history is too short")
    inputs = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
    return inputs, np.concatenate(labels).astype("float32")


def plan(data: Data, day: int, cost_for: dict[int, CostFunction]) -> list[Assignment]:
    """A layout per warehouse, planned on the evening of `day`."""
    state = product_state(data.lines, data.units, day)
    plans = []
    for w in range(len(data.layout.warehouse_ids)):
        products = data.products(w, day)
        need_kg, need_cm3 = face_need(data.layout, state.units_28[w, products], products)
        plans.append(assign(data.layout, w, products, cost_for[w], need_kg, need_cm3))
    return plans


def evaluate(
    data: Data, plans: list[Assignment], current: dict[tuple[int, int], int], start: int, end: int
) -> dict[str, float]:
    """Judge layouts on the real picks of days start..end against the current layout."""
    layout = data.layout
    old_time = new_time = 0.0
    old_dist, new_dist, weights = [], [], []
    broken = {"zone": 0, "overweight": 0, "overvolume": 0, "unplaced": 0}
    used, eligible, fills, moved, compared = set(), 0, [], 0, 0
    for plan_ in plans:
        w = plan_.warehouse
        picks, per_pick = data.period(w, start, end)
        for key, value in violations(layout, plan_).items():
            broken[key] += value
        eligible += int(
            np.sum((layout.bin_warehouse == layout.warehouse_ids[w]) & (layout.bin_zone >= 0))
        )
        placed = plan_.bins >= 0
        load = np.bincount(plan_.bins[placed], plan_.need_cm3[placed], len(layout.bin_ids))
        bins_used = np.flatnonzero(load > 0)
        used.update(bins_used.tolist())
        fills.extend((load[bins_used] / layout.bin_max_cm3[bins_used]).tolist())
        for p, b in zip(plan_.products[placed], plan_.bins[placed], strict=True):
            old = current.get((w, int(p)))
            if old is None:
                continue
            compared += 1
            moved += int(old != b)
            rate = picks[p]
            seconds = pick_seconds(layout, np.array([p, p]), np.array([old, b]), per_pick[p])
            old_time += rate * seconds[0]
            new_time += rate * seconds[1]
            old_dist.append(layout.bin_distance[old])
            new_dist.append(layout.bin_distance[b])
            weights.append(rate)
    total_violations = sum(broken.values())
    reduction = 1 - new_time / old_time if old_time else 0.0
    result = {
        "pick_time_reduction": reduction,
        "distance_reduction": (
            metrics.distance_reduction(old_dist, new_dist, weights) if sum(weights) else 0.0
        ),
        "pick_hours_per_day_before": old_time / 3600,
        "pick_hours_per_day_after": new_time / 3600,
        "violations": float(total_violations),
        **{f"violations_{k}": float(v) for k, v in broken.items()},
        "bins_used_share": len(used) / max(eligible, 1),
        "mean_volume_fill": float(np.mean(fills)) if fills else 0.0,
        "moved_share": moved / max(compared, 1),
        "products_compared": float(compared),
    }
    result[SELECTION_METRIC] = reduction if total_violations == 0 else -1.0
    return result


def current_layout(data: Data, current: dict[tuple[int, int], int], day: int) -> list[Assignment]:
    """Where the products are now, as assignments (for the reference row)."""
    state = product_state(data.lines, data.units, day)
    layouts = []
    for w in range(len(data.layout.warehouse_ids)):
        pairs = sorted((p, b) for (wh, p), b in current.items() if wh == w)
        products = np.array([p for p, _ in pairs], int)
        bins = np.array([b for _, b in pairs], int)
        need_kg, need_cm3 = face_need(data.layout, state.units_28[w, products], products)
        layouts.append(Assignment(w, products, bins, need_kg, need_cm3))
    return layouts


def run(
    database: Path = DEFAULT_DATABASE,
    *,
    models: Sequence[str] | None = None,
    config: ExperimentConfig | None = None,
    report: Reporter = print,
    write_report: Path | None = REPORT,
) -> SlottingRun:
    from models.slotting import ARCHITECTURES

    config = config or load_config(USE_CASE)
    names = list(config.models) if models is None else list(models)
    unknown = [n for n in names if n not in config.models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; configured: {list(config.models)}")
    engine = open_dataset(database)
    upgrade_database(database)
    version, data_version = keras_setup.new_version(), dataset_version(engine)
    first, last = history_range(engine)
    report(f"Slotting on {data_version}")
    data = Data(engine, first, last)
    split = chronological_split(
        first, last, validation_days=config.validation_days, test_days=config.test_days
    )
    train_end, valid_end = (split.train_end - first).days, (split.valid_end - first).days
    horizon = int(config.features.get("horizon", 28))
    snapshot_every = int(config.features.get("snapshot_every", 28))
    per_product = int(config.features.get("bins_per_product", 8))
    train_days = list(range(HISTORY_DAYS - 1, train_end - horizon + 1, snapshot_every))
    train_x, train_y = training_pairs(data, train_days, horizon, per_product, config.seed)
    valid_x, valid_y = training_pairs(data, [train_end], horizon, per_product, config.seed + 1)
    report(f"  {split.describe()}; {len(train_y):,} training pairs, {len(valid_y):,} validation")

    periods = {"validation": (train_end, valid_end), "test": (valid_end, data.days - 1)}
    current = {
        "validation": current_slots(engine, data.layout, split.train_end),
        "test": current_slots(engine, data.layout, split.valid_end),
    }

    def score(cost_maker) -> dict[str, dict[str, float]]:
        out = {}
        for name, (day, end) in periods.items():
            state = product_state(data.lines, data.units, day)
            cost_for = {w: cost_maker(w, state) for w in range(len(data.layout.warehouse_ids))}
            out[name] = evaluate(data, plan(data, day, cost_for), current[name], day + 1, end)
        return out

    # References, not candidates: the current layout, and a layout planned with perfect
    # knowledge of the coming picks (the best the optimizer could do: an upper bound).
    reference = {
        name: evaluate(data, current_layout(data, current[name], day), current[name], day + 1, end)
        for name, (day, end) in periods.items()
    }

    def oracle_maker(end_of: dict[int, int]):
        def maker(w, state):
            day = next(d for d, e in periods.values() if e == end_of[w])
            picks, per_pick = data.period(w, day + 1, end_of[w])

            def cost(products: np.ndarray, bins: np.ndarray) -> np.ndarray:
                return picks[products] * pick_seconds(
                    data.layout, products, bins, per_pick[products]
                )

            return cost

        return maker

    oracle = {}
    for name, (day, end) in periods.items():
        state = product_state(data.lines, data.units, day)
        maker = oracle_maker(dict.fromkeys(range(len(data.layout.warehouse_ids)), end))
        cost_for = {w: maker(w, state) for w in range(len(data.layout.warehouse_ids))}
        oracle[name] = evaluate(data, plan(data, day, cost_for), current[name], day + 1, end)

    results = []
    with timer() as elapsed:
        scored = score(lambda w, state: abc_cost(data.layout, state.picks_90[w]))
        results.append(ModelResult("abc_slotting", True, scored["validation"], scored["test"], 0))
        results[-1].seconds = elapsed()
    report(f"  {'abc_slotting':<24} test pick time -{scored['test']['pick_time_reduction']:.1%}")

    shapes = {k: v.shape[1:] for k, v in train_x.items()}
    for name in names:
        with timer() as elapsed:
            keras_setup.set_seeds(config.seed)
            model = ARCHITECTURES[name](shapes, config.model(name), config.learning_rate, train_x)
            artifact = keras_setup.artifact_path(USE_CASE, name, version)
            checkpoint = artifact.with_suffix(".checkpoint.keras")
            own = {t.name for t in model.inputs}
            fit = model.fit(
                {k: v for k, v in train_x.items() if k in own},
                train_y,
                validation_data=({k: v for k, v in valid_x.items() if k in own}, valid_y),
                epochs=config.max_epochs,
                batch_size=config.batch_size,
                verbose=0,
                callbacks=keras_setup.training_callbacks(checkpoint, patience=config.patience),
            )
            keras_setup.save_model(model, artifact)
            checkpoint.unlink(missing_ok=True)

            def cost_maker(w, state, model=model, own=own):
                def cost(products: np.ndarray, bins: np.ndarray) -> np.ndarray:
                    x = pair_features(data.layout, state, w, products, bins)
                    out = model.predict(
                        {k: v for k, v in x.items() if k in own}, batch_size=65536, verbose=0
                    )
                    return np.expm1(out.ravel())

                return cost

            scored = score(cost_maker)
            result = ModelResult(
                name,
                False,
                scored["validation"],
                scored["test"],
                0,
                params=config.model(name),
                artifact=artifact,
                epochs=len(fit.history["loss"]),
            )
            result.seconds = elapsed()
        results.append(result)
        report(
            f"  {name:<24} test pick time -{result.test['pick_time_reduction']:.1%} "
            f"({result.epochs} epochs, {result.seconds:.0f}s)"
        )

    selection = register_results(
        engine,
        results,
        use_case=USE_CASE,
        version=version,
        dataset_version=data_version,
        features=FEATURES,
        common_params={**config.features, "seed": config.seed},
        metric=SELECTION_METRIC,
        higher_is_better=True,
    )
    report(f"Selected: {selection.reason}")
    engine.dispose()
    outcome = SlottingRun(
        version, data_version, split.describe(), len(train_y), reference, oracle, results, selection
    )
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown_report(outcome), encoding="utf-8")
        report(f"Report: {write_report}")
    return outcome


def markdown_report(outcome: SlottingRun) -> str:
    columns = [
        "pick_time_reduction",
        "distance_reduction",
        "pick_hours_per_day_after",
        "violations",
        "bins_used_share",
        "mean_volume_fill",
        "moved_share",
    ]
    base = outcome.current["test"]
    lines = [
        "# Slotting: method comparison",
        "",
        f"- Dataset: `{outcome.dataset_version}`, training run `{outcome.version}`",
        f"- Split: {outcome.split_description}; {outcome.training_pairs:,} training pairs",
        "- Each method plans one pick-face bin per product and warehouse on the last day "
        "before the **test** period; it is judged with the real picks of the test period "
        "against the current layout (where the products were), which needs "
        f"{base['pick_hours_per_day_before']:.1f} picking hours per day "
        f"(estimated pick time model, see feature_engineering/slotting_features.py).",
        "- Hard rules (zone, weight, volume, every product placed) must have 0 violations; "
        "the selection uses the pick-time reduction.",
        "",
        "| Method | Type | " + " | ".join(columns) + " | Time |",
        "|---|---|" + "---:|" * (len(columns) + 1),
        "| current layout | reference | 0.000 | 0.000 | "
        f"{base['pick_hours_per_day_before']:.3f} | {base['violations']:.3f} | "
        f"{base['bins_used_share']:.3f} | {base['mean_volume_fill']:.3f} | 0.000 | - |",
        "| perfect foresight (upper bound) | reference | "
        + " | ".join(f"{outcome.oracle['test'][c]:.3f}" for c in columns)
        + " | - |",
    ]
    for r in sorted(outcome.results, key=lambda r: -r.test[SELECTION_METRIC]):
        name = f"**{r.name}** (selected)" if r.name == outcome.selection.model_name else r.name
        kind = "baseline" if r.is_baseline else "Keras + optimizer"
        values = " | ".join(f"{r.test[c]:.3f}" for c in columns)
        lines.append(f"| {name} | {kind} | {values} | {r.seconds:.0f} s |")
    lines += ["", f"**Selection:** {outcome.selection.reason}."]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train and compare slotting methods.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--models", nargs="+", help="networks to train (default: all)")
    args = parser.parse_args(argv)
    run(args.database, models=args.models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
