"""Write the list of backend API routes for the frontend tests.

Run from the project root after adding, removing or renaming an endpoint:

    python scripts/export_api_routes.py

It writes frontend/src/test/apiRoutes.json ("METHOD /path" under /api/v1, sorted). The
frontend's API tests check that every call the web app makes matches one of these
routes, and the backend tests fail when the file is out of date, so a renamed endpoint
cannot silently break a page.
"""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTES_FILE = PROJECT_ROOT / "frontend" / "src" / "test" / "apiRoutes.json"
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def api_routes() -> list[str]:
    os.environ.setdefault("APP_ENV", "test")
    from app.main import API_V1_PREFIX, app

    routes = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith(API_V1_PREFIX):
            continue
        for method in operations:
            routes.append(f"{method.upper()} {path.removeprefix(API_V1_PREFIX)}")
    return sorted(routes)


def render(routes: list[str]) -> str:
    return json.dumps(routes, indent=2) + "\n"


def main() -> int:
    ROUTES_FILE.write_text(render(api_routes()), encoding="utf-8")
    print(f"Wrote {ROUTES_FILE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
