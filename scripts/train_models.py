"""Train and compare the machine-learning models of all six use cases (Phase 8).

Run from the project root (virtual environment active, ml/requirements.txt installed),
after generating the dataset with scripts/generate_data.py:

    python scripts/train_models.py                              # all six, about 1 hour
    python scripts/train_models.py --use-case demand_forecasting reorder
    python scripts/train_models.py --quick                      # smoke test: 1 epoch each

Each use case trains its baselines and networks, registers every model with its metrics
in the database (model_versions, model_metrics), selects the best one and writes its
report to ml/evaluation/reports/. At the end the overview of all selected models is
written to ml/evaluation/reports/overview.md. Trained models are saved under
ml/artifacts/ (not in Git).
"""

import argparse
import sys
import time
from pathlib import Path

# The ML code (ml/) and the backend package (`app`) are importable from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

from data_generation.database import DEFAULT_DATABASE  # noqa: E402
from evaluation.compare_models import OVERVIEW, write_overview  # noqa: E402
from training.data import DatasetError, open_dataset  # noqa: E402
from training.use_cases import BY_NAME, USE_CASES, quick_config  # noqa: E402


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and compare all ML use cases.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--use-case",
        nargs="+",
        choices=list(BY_NAME),
        help="train only these use cases (default: all six)",
    )
    parser.add_argument(
        "--quick", action="store_true", help="1 epoch and small samples (checks the pipeline)"
    )
    parser.add_argument(
        "--overview", type=Path, default=OVERVIEW, help="where to write the overview"
    )
    parser.add_argument(
        "--no-reports",
        action="store_true",
        help="do not overwrite the per-use-case reports in ml/evaluation/reports/",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        open_dataset(args.database).dispose()
    except DatasetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    chosen = [BY_NAME[name] for name in args.use_case] if args.use_case else list(USE_CASES)
    print(
        f"Training {len(chosen)} use case(s) on {args.database}"
        + (" (quick)" if args.quick else "")
    )
    started = time.perf_counter()
    timings = []
    for number, info in enumerate(chosen, 1):
        print(f"\n[{number}/{len(chosen)}] {info.title}")
        begin = time.perf_counter()
        options = {"report": lambda line: print(f"  {line}")}
        if args.quick:
            options["config"] = quick_config(info.name)
        if args.no_reports:
            options["write_report"] = None
        outcome = info.runner()(args.database, **options)
        timings.append((info.title, outcome.selection.model_name, time.perf_counter() - begin))

    engine = open_dataset(args.database)
    path = write_overview(engine, args.overview)
    engine.dispose()
    minutes, seconds = divmod(round(time.perf_counter() - started), 60)
    print(f"\nDone in {minutes} min {seconds} s.")
    for title, selected, took in timings:
        print(f"  {title:<26} selected {selected:<28} {took:>6.0f} s")
    print(f"Overview: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
