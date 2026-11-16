"""Generate the synthetic two-year dataset, load it into SQLite and validate it.

Run from the project root (virtual environment active, ml/requirements.txt installed):

    python scripts/generate_data.py                      # small: 500 orders, about 10 s
    python scripts/generate_data.py --size medium        # 50,000 orders, a few minutes
    python scripts/generate_data.py --size full          # 500,000 orders, about 20 min
    python scripts/generate_data.py --size full --replace --seed 7

The database is database/warehouse_synthetic.db (change with --database); it is never
overwritten without --replace. The same size, seed and end date always give the same
data. Steps: master data and layout, two years day by day, the application's alerts on
the last day, demo logins (development only), and the validation report.

To open it in the application, point the backend at it, e.g. in the project's .env:

    DATABASE_URL=sqlite:///./database/warehouse_synthetic.db
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

# The generator (ml/) and the backend package (`app`) are importable from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "ml"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from data_generation.config import DEFAULT_SEED, SIZE_NAMES, get_config  # noqa: E402
from data_generation.database import DEFAULT_DATABASE, GenerationError  # noqa: E402
from data_generation.pipeline import generate  # noqa: E402
from data_validation.validate_dataset import (  # noqa: E402
    default_report_path,
    validate_dataset,
)
from seed_database import DEMO_PASSWORD, DEMO_USERS  # noqa: E402  (the same demo logins)
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import INSECURE_SECRET_ALLOWED_ENVS, get_settings  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services.user_service import UserService  # noqa: E402

STAGES = 5


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and validate the synthetic dataset.")
    parser.add_argument("--size", choices=SIZE_NAMES, default="small")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--replace", action="store_true", help="delete an existing database")
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="last day of the history, YYYY-MM-DD (default: today)",
    )
    parser.add_argument("--no-demo-users", action="store_true", help="do not add demo logins")
    return parser.parse_args(argv)


def add_demo_users(db: Session) -> int:
    """The demo logins (the database is always new, so none exist yet)."""
    service = UserService(db)
    for email, name, role in DEMO_USERS:
        service.create_user(
            UserCreate(email=email, full_name=name, password=DEMO_PASSWORD, roles=[role])
        )
    return len(DEMO_USERS)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = get_config(args.size, seed=args.seed, end_date=args.end_date)
    demo_users = not args.no_demo_users
    if demo_users and get_settings().app_env not in INSECURE_SECRET_ALLOWED_ENVS:
        print("Demo logins are only added in development; continuing without them.")
        demo_users = False
    started = time.perf_counter()
    print(
        f"Generating the {config.name} dataset (seed {config.seed}, {config.orders:,} orders) "
        f"into {args.database}"
    )
    try:
        result = generate(config, args.database, replace=args.replace, report=print, stages=STAGES)
    except GenerationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"[4/{STAGES}] Demo logins")
    if demo_users:
        with Session(result.engine) as db:
            created = add_demo_users(db)
        print(f"  {created} created: {', '.join(e for e, _, _ in DEMO_USERS)}")
        print(f"  password: {DEMO_PASSWORD} (local development only)")
    else:
        print("  skipped")

    print(f"[5/{STAGES}] Validation")
    report = validate_dataset(result.engine, config)
    path = default_report_path(args.database)
    path.write_text(report.to_markdown(), encoding="utf-8")
    for check in report.failures:
        print(f"  FAILED {check.group}: {check.name}: {check.value} (expected {check.expected})")
    print(
        f"  {report.count('pass')} passed, {report.count('fail')} failed, "
        f"{report.count('skip')} skipped. Report: {path}"
    )
    result.engine.dispose()

    minutes, seconds = divmod(round(time.perf_counter() - started), 60)
    print(f"\nDone in {minutes} min {seconds} s.")
    for table, rows in sorted(result.ctx.writer.counts.items(), key=lambda item: -item[1])[:8]:
        print(f"  {table:<22} {rows:>12,}")
    print(
        "\nTo use it in the application, set in .env:\n"
        f"  DATABASE_URL=sqlite:///{database_setting(args.database)}"
    )
    return 0 if report.passed else 1


def database_setting(path: Path) -> str:
    """The DATABASE_URL path: relative to the project root when inside it."""
    resolved = path.resolve()
    try:
        return "./" + resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
