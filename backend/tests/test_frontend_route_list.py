"""The frontend's copy of the API routes (frontend/src/test/apiRoutes.json) is current.

The frontend tests check every API call of the web app against that file; if an
endpoint is added, removed or renamed, regenerate it: python scripts/export_api_routes.py
"""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_api_routes.py"


def test_route_list_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location("export_api_routes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = json.loads(module.ROUTES_FILE.read_text(encoding="utf-8"))
    assert (
        saved == module.api_routes()
    ), "frontend/src/test/apiRoutes.json is out of date: run python scripts/export_api_routes.py"
    assert "POST /auth/login" in saved and "GET /ml/accuracy" in saved
