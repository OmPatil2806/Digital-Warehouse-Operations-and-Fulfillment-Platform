"""Create the first administrator account.

Run from the project root (with the virtual environment active):

    python scripts/create_admin.py

You are asked for the email, full name and password (typed hidden, entered twice).
Nothing is stored in files or in your shell history.

For automation (e.g. a demo setup), values can also come from options/environment:

    python scripts/create_admin.py --email admin@example.com --name "Admin"
    # password from the ADMIN_PASSWORD environment variable (never as a command option)
"""

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

# Make the backend package (`app`) importable when running from the project root.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database.session import SessionLocal  # noqa: E402
from app.exceptions import AppError  # noqa: E402
from app.models.user import RoleName, User  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services.user_service import UserService  # noqa: E402

SessionFactory = Callable[[], AbstractContextManager[Session]]


class CreateAdminError(Exception):
    """A problem the user can fix; shown without a traceback."""


def create_admin(db: Session, *, email: str, full_name: str, password: str) -> User:
    """Validate the input and create a user with the admin role."""
    if not inspect(db.get_bind()).has_table("users"):
        raise CreateAdminError(
            "The database has no users table yet. Run `alembic upgrade head` in backend/ first."
        )
    try:
        data = UserCreate(
            email=email, full_name=full_name, password=password, roles=[RoleName.ADMIN]
        )
    except ValidationError as exc:
        messages = "; ".join(error["msg"].removeprefix("Value error, ") for error in exc.errors())
        raise CreateAdminError(f"Invalid input: {messages}") from exc
    try:
        return UserService(db).create_user(data)
    except AppError as exc:
        raise CreateAdminError(exc.message) from exc


def _prompt(label: str, default: str | None) -> str:
    return default if default else input(f"{label}: ").strip()


def _prompt_password() -> str:
    from_env = os.environ.get("ADMIN_PASSWORD")
    if from_env:
        return from_env
    password = getpass.getpass("Password (min 8 chars, letters and digits): ")
    if password != getpass.getpass("Repeat password: "):
        raise CreateAdminError("Passwords do not match")
    return password


def main(argv: list[str] | None = None, session_factory: SessionFactory = SessionLocal) -> int:
    parser = argparse.ArgumentParser(description="Create an administrator account.")
    parser.add_argument("--email", help="admin email (asked if omitted)")
    parser.add_argument("--name", help="admin full name (asked if omitted)")
    args = parser.parse_args(argv)

    print("Create administrator account\n")
    try:
        email = _prompt("Email", args.email)
        full_name = _prompt("Full name", args.name)
        password = _prompt_password()
        with session_factory() as db:
            admin = create_admin(db, email=email, full_name=full_name, password=password)
            print(f"\nAdmin created: {admin.email} (id {admin.id})")
            print("Log in at POST /api/v1/auth/login or in the web app.")
    except CreateAdminError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
