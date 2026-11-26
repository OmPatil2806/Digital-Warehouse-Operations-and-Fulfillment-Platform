"""Check the selected ML models and their latest predictions (Phase 10).

Run from the project root after scoring (python scripts/score_models.py):

    python scripts/check_models.py
    python scripts/check_models.py --database database/warehouse_synthetic.db

For every use case: the selected network loads from its saved file and gives finite
outputs of the right shape; the stored predictions cover what they should (every
product, every forecast day, every parcel on its way) with finite, consistent values.
Exit code 1 when a check fails (CI runs it after scoring).
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))

from data_generation.database import DEFAULT_DATABASE  # noqa: E402
from inference.checks import check  # noqa: E402
from training.data import DatasetError, open_dataset  # noqa: E402
from training.use_cases import BY_NAME  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the selected models and predictions.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--use-case", nargs="+", choices=list(BY_NAME))
    args = parser.parse_args(argv)
    try:
        engine = open_dataset(args.database)
    except DatasetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    results = check(engine, args.use_case)
    engine.dispose()
    print(f"{'Use case':<26} {'Model':<28} {'Rows':>8}  Result")
    for r in results:
        verdict = "ok" if r.ok else "FAILED: " + "; ".join(r.problems)
        print(f"{r.use_case:<26} {r.model_name or '-':<28} {r.rows:>8,}  {verdict}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} use cases passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
