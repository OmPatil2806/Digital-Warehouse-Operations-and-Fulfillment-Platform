"""Tests for scripts/create_admin.py."""

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.repositories.user_repository import UserRepository
from tests.factories import create_user

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_admin.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_admin_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session_factory(db: Session):  # noqa: ANN201
    """Give the script the test session (rolled back after the test) instead of a real one."""

    @contextmanager
    def _factory() -> Iterator[Session]:
        yield db

    return _factory


def answer(monkeypatch: pytest.MonkeyPatch, *, inputs: list[str], passwords: list[str]) -> None:
    input_values, password_values = iter(inputs), iter(passwords)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(input_values))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": next(password_values))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)


def test_interactive_creation(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    answer(monkeypatch, inputs=["Boss@Example.com", "The Boss"], passwords=["Adm1n-pass"] * 2)

    assert script.main([], session_factory=session_factory(db_session)) == 0

    admin = UserRepository(db_session).get_by_email("boss@example.com")
    assert admin is not None
    assert admin.role_names == {"admin"}
    assert admin.full_name == "The Boss"
    assert verify_password("Adm1n-pass", admin.hashed_password)
    assert "Admin created: boss@example.com" in capsys.readouterr().out


def test_options_and_env_password(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADMIN_PASSWORD", "Env-passw0rd")

    code = script.main(
        ["--email", "auto@example.com", "--name", "Auto Admin"],
        session_factory=session_factory(db_session),
    )

    assert code == 0
    assert UserRepository(db_session).get_by_email("auto@example.com") is not None


def test_passwords_must_match(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    answer(monkeypatch, inputs=["x@example.com", "X"], passwords=["Adm1n-pass", "Different-1"])

    assert script.main([], session_factory=session_factory(db_session)) == 1
    assert "Passwords do not match" in capsys.readouterr().err


def test_weak_password_is_explained(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    answer(monkeypatch, inputs=["y@example.com", "Y"], passwords=["weak", "weak"])

    assert script.main([], session_factory=session_factory(db_session)) == 1
    assert "at least 8 characters" in capsys.readouterr().err


def test_existing_email_is_refused(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    create_user(db_session, "taken@example.com")
    answer(monkeypatch, inputs=["taken@example.com", "T"], passwords=["Adm1n-pass"] * 2)

    assert script.main([], session_factory=session_factory(db_session)) == 1
    assert "already exists" in capsys.readouterr().err


def test_missing_tables_give_a_helpful_message(script: ModuleType, tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with Session(engine) as empty_db, pytest.raises(script.CreateAdminError, match="alembic"):
        script.create_admin(empty_db, email="a@example.com", full_name="A", password="Adm1n-pass")
    engine.dispose()
