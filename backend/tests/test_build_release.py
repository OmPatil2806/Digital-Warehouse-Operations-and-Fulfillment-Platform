"""The release package script (scripts/build_release.py)."""

import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_release.py"


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("build_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def built_web_app(tmp_path: Path) -> Path:
    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


def test_all_parts_of_the_project_have_the_same_version(release) -> None:
    versions = release.code_versions()
    assert set(versions) == set(release.VERSION_FILES)
    assert len(set(versions.values())) == 1, versions


def test_a_release_version_must_match_the_code(release) -> None:
    code = next(iter(release.code_versions().values()))
    assert release.resolve_version(f"v{code}") == code
    assert release.resolve_version(None) == f"{code}-snapshot"
    with pytest.raises(release.ReleaseError, match="does not match"):
        release.resolve_version("v99.0.0")
    with pytest.raises(release.ReleaseError, match="looks like v1.0.0"):
        release.resolve_version("1.0")


def test_different_versions_in_the_code_are_refused(release, tmp_path: Path) -> None:
    for path in release.VERSION_FILES:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.endswith(".json"):
            target.write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
        elif path.endswith("config.py"):
            target.write_text('    app_version: str = "1.0.0"\n', encoding="utf-8")
        else:
            target.write_text('version = "0.9.0"\n', encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="different versions"):
        release.resolve_version(None, tmp_path)


def test_the_package_holds_the_project_and_the_web_app(
    release, built_web_app: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    archive = release.build(None, output=out, frontend_dist=built_web_app)
    folder = archive.stem
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        guide = zf.read(f"{folder}/INSTALL.md").decode()
    for expected in (
        "README.md",
        "LICENSE",
        ".env.example",
        "backend/app/main.py",
        "backend/alembic.ini",
        "frontend/dist/index.html",
        "frontend/dist/assets/app.js",
        "scripts/create_admin.py",
        "docs/security.md",
        "INSTALL.md",
    ):
        assert f"{folder}/{expected}" in names, expected
    # Only tracked files: no local secrets, databases or trained models.
    assert not any(n.endswith((".env", ".db", ".keras")) for n in names)
    assert not any("/node_modules/" in n or "__pycache__" in n for n in names)
    assert "alembic upgrade head" in guide
    digest, name = (out / "SHA256SUMS").read_text().split()
    assert name == archive.name and digest == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_the_web_app_must_be_built_first(release, tmp_path: Path, capsys) -> None:
    with pytest.raises(release.ReleaseError, match="npm run build"):
        release.build(None, output=tmp_path, frontend_dist=tmp_path / "missing")
    assert (
        release.main(["--frontend-dist", str(tmp_path / "missing"), "--output", str(tmp_path)]) == 1
    )
    assert "npm run build" in capsys.readouterr().err
