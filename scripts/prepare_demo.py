"""Prepare a demonstration database in one command (Phase 10).

Run from the project root (virtual environment active, ml/requirements.txt installed):

    python scripts/prepare_demo.py                  # medium dataset, full training
    python scripts/prepare_demo.py --size small     # a few minutes, for a quick try
    python scripts/prepare_demo.py --size full      # the full volume (about 2 hours)

It runs, in order: generate and validate the dataset with the demo logins (the customer
login linked to a busy customer), train and compare all six ML use cases, score them,
check the models and predictions, and backtest the last 30 days so the "predictions vs
reality" view has data. At the end it prints how to start the platform. The committed
model reports (ml/evaluation/reports/, full dataset) are left as they are; the
comparison of this run is written next to the database (<name>_models.md). The walkthrough
for a presentation is in docs/demo-scenario.md.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "database" / "warehouse_demo.db"


def steps(database: Path, size: str, quick: bool, replace: bool) -> list[tuple[str, list[str]]]:
    db = ["--database", str(database)]
    generate = ["generate_data.py", "--size", size, *db] + (["--replace"] if replace else [])
    return [
        ("Generate and validate the dataset", generate),
        (
            "Train and compare the models",
            # The committed reports in ml/evaluation/reports/ describe the full dataset:
            # a demo run keeps them and writes its overview next to its database.
            ["train_models.py", *db, "--no-reports", "--overview", str(overview(database))]
            + (["--quick"] if quick else []),
        ),
        ("Score with the selected models", ["score_models.py", *db]),
        ("Check the models and predictions", ["check_models.py", *db]),
        ("Backtest the last 30 days", ["score_models.py", *db, "--backtest", "30"]),
    ]


def overview(database: Path) -> Path:
    return database.with_name(f"{database.stem}_models.md")


def database_setting(path: Path) -> str:
    try:
        return f"sqlite:///./{path.resolve().relative_to(PROJECT_ROOT).as_posix()}"
    except ValueError:
        return f"sqlite:///{path.resolve().as_posix()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a demonstration database.")
    parser.add_argument("--size", choices=("small", "medium", "full"), default="medium")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--quick", action="store_true", help="1 epoch per model (faster)")
    parser.add_argument("--replace", action="store_true", help="replace an existing database")
    args = parser.parse_args(argv)
    if args.database.exists() and not args.replace:
        print(f"Error: {args.database} exists. Use --replace to build it again.", file=sys.stderr)
        return 1

    started = time.perf_counter()
    plan = steps(args.database, args.size, args.quick, args.replace)
    for number, (title, command) in enumerate(plan, 1):
        print(f"\n=== [{number}/{len(plan)}] {title}", flush=True)
        script, *options = command
        result = subprocess.run(  # noqa: S603 (the project's own scripts, fixed arguments)
            [sys.executable, str(PROJECT_ROOT / "scripts" / script), *options],
            cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            print(f"\nStopped: step {number} ({title}) failed.", file=sys.stderr)
            return result.returncode

    minutes = round((time.perf_counter() - started) / 60)
    print(f"""
The demo is ready ({minutes} min). To start the platform:

  1. In .env:  DATABASE_URL={database_setting(args.database)}
  2. API:      cd backend  then  uvicorn app.main:app --port 8000
  3. Web app:  cd frontend  then  npm run dev   (open http://localhost:5173)

Logins (password Demo-pass-123): manager@example.com, staff@example.com,
customer@example.com, admin@example.com. Walkthrough: docs/demo-scenario.md
Model comparison of this run: {overview(args.database)}""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
