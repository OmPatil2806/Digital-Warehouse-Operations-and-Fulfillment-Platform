"""Build the release package: a zip with the project and the built web app (Phase 10).

Run from the project root after building the frontend (cd frontend; npm run build):

    python scripts/build_release.py                    # snapshot of the current version
    python scripts/build_release.py --version v1.0.0   # a release: must match the code

The zip `dist/warehouse-platform-<version>.zip` holds every file tracked by Git (so no
local databases, .env files, caches or trained models), the built web app in
frontend/dist/, and INSTALL.md with the steps to run it. Next to it, SHA256SUMS lets
anyone verify the download. A release version must equal the version in the code
(backend, ML and frontend), so a tag can never publish a package of another version.
The delivery workflow runs this script and attaches both files to the GitHub Release.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NAME = "warehouse-platform"

# Where each part of the project states its version.
VERSION_FILES = {
    "backend/pyproject.toml": r'^version = "([^"]+)"',
    "ml/pyproject.toml": r'^version = "([^"]+)"',
    "backend/app/core/config.py": r'app_version: str = "([^"]+)"',
    "frontend/package.json": None,  # JSON "version"
}


class ReleaseError(Exception):
    """A problem the user can fix (shown without a traceback)."""


def code_versions(root: Path = PROJECT_ROOT) -> dict[str, str]:
    versions = {}
    for path, pattern in VERSION_FILES.items():
        text = (root / path).read_text(encoding="utf-8")
        if pattern is None:
            versions[path] = json.loads(text)["version"]
        else:
            found = re.search(pattern, text, flags=re.MULTILINE)
            if not found:
                raise ReleaseError(f"no version found in {path}")
            versions[path] = found.group(1)
    return versions


def resolve_version(requested: str | None, root: Path = PROJECT_ROOT) -> str:
    """The package version: the requested release (checked against the code) or a
    snapshot of the code's version."""
    versions = code_versions(root)
    if len(set(versions.values())) != 1:
        listed = ", ".join(f"{path} {v}" for path, v in versions.items())
        raise ReleaseError(f"the parts of the project have different versions: {listed}")
    code = next(iter(versions.values()))
    if requested is None:
        return f"{code}-snapshot"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", requested):
        raise ReleaseError(f"a release version looks like v1.0.0, not {requested!r}")
    if requested.removeprefix("v") != code:
        raise ReleaseError(
            f"{requested} does not match the version in the code ({code}): "
            "raise the version in the code first"
        )
    return requested.removeprefix("v")


def tracked_files(root: Path = PROJECT_ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607 (git from PATH, fixed arguments)
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(name for name in result.stdout.split("\0") if name)


def install_guide(version: str, commit: str) -> str:
    return f"""# Digital Warehouse Operations and Fulfillment Platform {version}

Built {datetime.now(UTC):%Y-%m-%d} from commit {commit}. The full documentation is in
README.md and docs/.

## Contents

- `backend/`: the API (FastAPI) with its database migrations
- `frontend/dist/`: the built web app (static files); `frontend/` also holds its source
- `ml/`: data generation, training, scoring and the model comparison reports
- `scripts/`: demo data, data generation, training, scoring, checks, speed check
- `docs/`: security review and speed check

Not included: databases, trained models (`ml/artifacts/`), and `.env`.

## Run it (Python 3.12 and, to serve the web app, Node.js 22)

1. Create a virtual environment and install the backend:
   `python -m venv .venv`, activate it, then `pip install -r backend/requirements.txt`
2. Copy `.env.example` to `.env`. For anything beyond your own computer, set
   `APP_ENV=production`, a long random `SECRET_KEY`, and `CORS_ORIGINS` to the web app's
   address.
3. Create the database: `cd backend` then `alembic upgrade head`
4. Add users: `python ../scripts/create_admin.py` (or demo data in development:
   `python ../scripts/seed_database.py`)
5. Start the API: `uvicorn app.main:app --port 8000` (docs at http://localhost:8000/docs)
6. Serve the web app: `cd frontend`, `npm ci`, `npx vite preview --port 5173`, then open
   http://localhost:5173. Any static web server works if it answers unknown paths with
   `index.html`. The web app calls the API at http://localhost:8000/api/v1; for another
   address, set `VITE_API_BASE_URL` in `.env` and rebuild with `npm run build`.

## Verify the download

`sha256sum -c SHA256SUMS` (Linux/macOS) or `Get-FileHash <zip> -Algorithm SHA256`
(Windows PowerShell), and compare with the value in SHA256SUMS.
"""


def build(
    version: str | None,
    *,
    output: Path,
    frontend_dist: Path,
    root: Path = PROJECT_ROOT,
) -> Path:
    resolved = resolve_version(version, root)
    if not (frontend_dist / "index.html").is_file():
        raise ReleaseError(
            f"no built web app in {frontend_dist}: run `npm run build` in frontend/ first"
        )
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 (git from PATH, fixed arguments)
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout.strip()
    folder = f"{NAME}-{resolved}"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{folder}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in tracked_files(root):
            path = root / name
            if path.is_file():  # a tracked file deleted locally is skipped
                zf.write(path, f"{folder}/{name}")
        for path in sorted(p for p in frontend_dist.rglob("*") if p.is_file()):
            zf.write(path, f"{folder}/frontend/dist/{path.relative_to(frontend_dist).as_posix()}")
        zf.writestr(f"{folder}/INSTALL.md", install_guide(resolved, commit or "unknown"))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    (output / "INSTALL.md").write_text(install_guide(resolved, commit or "unknown"), "utf-8")
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the release zip.")
    parser.add_argument("--version", help="release version such as v1.0.0 (default: snapshot)")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument("--frontend-dist", type=Path, default=PROJECT_ROOT / "frontend" / "dist")
    args = parser.parse_args(argv)
    try:
        archive = build(args.version, output=args.output, frontend_dist=args.frontend_dist)
    except ReleaseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(archive) as zf:
        count = len(zf.namelist())
    print(f"Built {archive} ({count} files, {archive.stat().st_size / 1e6:.1f} MB)")
    print(f"Checksum in {archive.parent / 'SHA256SUMS'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
