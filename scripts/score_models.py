"""Score all ML use cases with their selected models and store the predictions (Phase 9).

Run from the project root after training (python scripts/train_models.py):

    python scripts/score_models.py                         # all six use cases
    python scripts/score_models.py --use-case reorder delay_prediction

Predictions are made "as of" the last day of data and stored in the prediction tables
(demand_forecasts, reorder_recommendations, movement_classifications,
slotting_recommendations, delay_predictions, product_recommendations), where the
application reads them. Every run adds new rows, so earlier predictions stay available.
"""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

from data_generation.database import DEFAULT_DATABASE  # noqa: E402
from inference.score import score  # noqa: E402
from training.data import DatasetError, open_dataset  # noqa: E402
from training.use_cases import BY_NAME  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the ML use cases and store predictions.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--use-case", nargs="+", choices=list(BY_NAME))
    args = parser.parse_args(argv)
    try:
        open_dataset(args.database).dispose()
    except DatasetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Scoring with the selected models on {args.database}")
    started = time.perf_counter()
    results = score(args.database, use_cases=args.use_case)
    skipped = [r.use_case for r in results if r.model_name is None]
    print(f"Done in {time.perf_counter() - started:.0f} s.")
    if skipped:
        print(f"No selected model for: {', '.join(skipped)}. Train them first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
