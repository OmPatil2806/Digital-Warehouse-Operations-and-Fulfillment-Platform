"""The overview of all use cases and the one-command training script."""

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import Engine

from data_generation.context import GenerationContext
from data_generation.database import prepare_database
from evaluation.compare_models import latest_runs, overview_markdown, write_overview
from registry.register_model import register_model, select_best
from training.config import load_config
from training.use_cases import BY_NAME, USE_CASES, quick_config

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "train_models.py"
Simulated = tuple[GenerationContext, Engine, dict]


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("train_models_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add(
    engine: Engine,
    use_case: str,
    name: str,
    value: float,
    metric: str,
    *,
    baseline: bool,
    version: str = "v1",
) -> int:
    return register_model(
        engine,
        use_case=use_case,
        model_name=name,
        version=version,
        dataset_version="orders500-to2026-11-10-abc",
        features=["x"],
        hyperparameters={},
        metrics={"test": {metric: value}},
        artifact_path=None if baseline else f"artifacts/{name}.keras",
        is_baseline=baseline,
        train_seconds=2.0,
    )


# ------------------------------------------------------------------- use cases
def test_six_use_cases_with_configs() -> None:
    assert [u.name for u in USE_CASES] == [
        "demand_forecasting",
        "reorder",
        "movement_classification",
        "slotting",
        "delay_prediction",
        "recommendation",
    ]
    for info in USE_CASES:
        module = importlib.import_module(info.module)
        assert info.name == module.USE_CASE and info.metric == module.SELECTION_METRIC
        assert callable(info.runner()) and load_config(info.name).models


def test_quick_config_is_small() -> None:
    quick = quick_config("movement_classification")
    assert quick.max_epochs == 1 and quick.patience == 1
    assert all(
        p.get("epochs", 2) <= 2 and p.get("pretrain_epochs", 2) <= 2 for p in quick.models.values()
    )
    assert quick.features["stability_runs"] == 2
    assert quick_config("reorder").features["max_train_rows"] == 5000
    assert quick_config("recommendation").features["eval_queries"] == 200


# -------------------------------------------------------------------- overview
def test_overview_of_the_latest_runs(tmp_path: Path) -> None:
    engine = prepare_database(tmp_path / "registry.db")
    # demand: lower is better; the network wins
    ids = [
        add(engine, "demand_forecasting", "moving_average", 0.40, "wape_totals", baseline=True),
        add(engine, "demand_forecasting", "lstm", 0.30, "wape_totals", baseline=False),
    ]
    select_best(engine, "demand_forecasting", ids, metric="wape_totals", higher_is_better=False)
    # an older run must not appear
    add(engine, "demand_forecasting", "gru", 0.10, "wape_totals", baseline=False, version="v0")
    # recommendation: higher is better; the baseline is kept
    ids = [
        add(
            engine, "recommendation", "frequently_bought_together", 0.4, "ndcg_at_10", baseline=True
        ),
        add(engine, "recommendation", "two_tower", 0.3, "ndcg_at_10", baseline=False),
    ]
    select_best(engine, "recommendation", ids, metric="ndcg_at_10", higher_is_better=True)
    # movement: an unusable network shows as such
    ids = [
        add(engine, "movement_classification", "abc", 0.28, "selection_score", baseline=True),
        add(engine, "movement_classification", "dec", -1.0, "selection_score", baseline=False),
    ]
    select_best(
        engine, "movement_classification", ids, metric="selection_score", higher_is_better=True
    )

    runs = latest_runs(engine)
    assert [r.info.name for r in runs] == [
        "demand_forecasting",
        "movement_classification",
        "recommendation",
    ]  # in use-case order, untrained ones left out
    demand = runs[0]
    assert [m.model_name for m in demand.models] == ["lstm", "moving_average"]  # best first
    assert demand.gain == pytest.approx(0.25)  # (0.40 - 0.30) / 0.40
    assert runs[2].gain is None and runs[2].best_network.model_name == "two_tower"
    text = overview_markdown(runs)
    assert "| Demand forecasting | **lstm** |" in text and "+25.0%" in text
    assert "**frequently_bought_together** (baseline)" in text and "baseline kept" in text
    assert "dec not usable" in text and "gru" not in text
    assert "[recommendation.md](recommendation.md)" in text
    path = write_overview(engine, tmp_path / "out" / "overview.md")
    assert path.read_text() == text
    assert "No trained models yet" in overview_markdown([])


# ------------------------------------------------------------- training script
def test_script_runs_the_chosen_use_cases(
    script: ModuleType, with_orders: Simulated, tmp_path: Path, monkeypatch, capsys
) -> None:
    _, engine, _ = with_orders
    calls = []

    def fake_runner(info):
        def run(database, **options):
            calls.append((info.name, database, sorted(options)))
            options["report"]("trained")
            return SimpleNamespace(selection=SimpleNamespace(model_name=f"{info.name}_best"))

        return run

    for info in USE_CASES:
        monkeypatch.setattr(type(info), "runner", lambda self: fake_runner(self))
    database = Path(str(engine.url.database))
    overview = tmp_path / "overview.md"
    assert (
        script.main(
            [
                "--database",
                str(database),
                "--use-case",
                "reorder",
                "slotting",
                "--quick",
                "--no-reports",
                "--overview",
                str(overview),
            ]
        )
        == 0
    )
    assert [c[0] for c in calls] == ["reorder", "slotting"]
    assert calls[0][2] == ["config", "report", "write_report"]
    out = capsys.readouterr().out
    assert "[1/2] Reorder recommendation" in out and "  trained" in out
    assert "selected slotting_best" in out and overview.exists()

    calls.clear()
    assert script.main(["--database", str(database), "--overview", str(overview)]) == 0
    assert [c[0] for c in calls] == list(BY_NAME) and calls[0][2] == ["report"]


def test_script_needs_a_dataset(script: ModuleType, tmp_path: Path, capsys) -> None:
    assert script.main(["--database", str(tmp_path / "missing.db")]) == 1
    assert "generate_data.py" in capsys.readouterr().err
