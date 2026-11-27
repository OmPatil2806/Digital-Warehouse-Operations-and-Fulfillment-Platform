"""The generated reference documentation (docs/openapi.json, the endpoint list in
docs/api.md and the table reference in docs/database.md) matches the code.

When this fails after changing an endpoint or a model: python scripts/generate_docs.py
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_docs.py"


def _load():
    spec = importlib.util.spec_from_file_location("generate_docs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_documentation_is_up_to_date() -> None:
    module = _load()
    stale = [
        path.name
        for path, content in module.outputs().items()
        if path.read_text(encoding="utf-8") != content
    ]
    assert stale == [], f"out of date: {stale}. Run: python scripts/generate_docs.py"


def test_every_table_and_endpoint_is_documented() -> None:
    from app.database.base import Base
    from app.main import app

    database = (SCRIPT.parents[1] / "docs" / "database.md").read_text(encoding="utf-8")
    api = (SCRIPT.parents[1] / "docs" / "api.md").read_text(encoding="utf-8")
    for table in Base.metadata.tables:
        assert f"#### `{table}`" in database, table
    for path in app.openapi()["paths"]:
        assert f"`{path}`" in api, path
    assert "Integer auto-increment primary key" not in database  # every table described
