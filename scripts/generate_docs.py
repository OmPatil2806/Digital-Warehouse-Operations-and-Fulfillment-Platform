"""Generate the reference parts of the documentation from the code (Phase 10).

Run from the project root after changing an endpoint or a database model:

    python scripts/generate_docs.py           # rewrite the generated parts
    python scripts/generate_docs.py --check   # only check they are current (CI)

It writes:

- docs/openapi.json: the API description (OpenAPI 3) the backend serves at /openapi.json;
- docs/api.md, between the "endpoints" markers: every endpoint, grouped by area;
- docs/database.md, between the "schema" markers: a diagram per area of the data model
  and every table with its columns, types and references.

The rest of those two files is written by hand. The backend tests fail when the
generated parts are out of date, so the reference can never drift from the code.
"""

import argparse
import inspect
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = PROJECT_ROOT / "docs"
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# Model module -> area of the data model, in the order they are documented.
AREAS = {
    "user": "Users and security",
    "catalog": "Catalog and suppliers",
    "warehouse": "Warehouse layout",
    "inventory": "Inventory",
    "order": "Orders, returns and customers",
    "fulfillment": "Picking and packing",
    "shipment": "Shipping",
    "purchase": "Purchasing",
    "audit": "Alerts and audit",
    "ml": "ML model registry",
    "ml_results": "ML predictions",
}
TABLE_MODULE = {"user_roles": "user"}  # association table without a model class


def _start(name: str) -> str:
    return f"<!-- generated:{name}:start (scripts/generate_docs.py) -->"


def _end(name: str) -> str:
    return f"<!-- generated:{name}:end -->"


def replace_section(text: str, name: str, content: str) -> str:
    start, end = _start(name), _end(name)
    if start not in text or end not in text:
        raise SystemExit(f"Error: the markers for '{name}' are missing")
    before = text[: text.index(start) + len(start)]
    after = text[text.index(end) :]
    return f"{before}\n\n{content.strip()}\n\n{after}"


# ----------------------------------------------------------------------- the API
def openapi() -> dict:
    from app.main import app

    return app.openapi()


def endpoints_markdown(spec: dict) -> str:
    by_tag: dict[str, list[tuple[str, str, str, bool]]] = {}
    for path, operations in spec["paths"].items():
        for method, op in operations.items():
            tag = (op.get("tags") or ["Other"])[0]
            by_tag.setdefault(tag, []).append(
                (method.upper(), path, op.get("summary", ""), bool(op.get("security")))
            )
    total = sum(len(rows) for rows in by_tag.values())
    lines = [f"{total} endpoints. 🔒 = needs a login token (`Authorization: Bearer ...`)."]
    for tag, rows in by_tag.items():
        lines += ["", f"### {tag}", "", "| | Method | Path | What it does |", "|---|---|---|---|"]
        for method, path, summary, secured in rows:
            lock = "🔒" if secured else ""
            lines.append(f"| {lock} | {method} | `{path}` | {summary} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------- database
def _tables():
    import app.models  # noqa: F401  (registers every model)
    from app.database.base import Base

    classes = {m.class_.__table__.name: m.class_ for m in Base.registry.mappers}
    for name, table in Base.metadata.tables.items():
        cls = classes.get(name)
        module = TABLE_MODULE.get(name) or cls.__module__.rsplit(".", 1)[-1]
        own_doc = cls.__dict__.get("__doc__") if cls else None
        doc = inspect.cleandoc(own_doc).split("\n\n")[0].replace("\n", " ") if own_doc else ""
        yield module, name, table, doc or "Which user has which role."


def _type(column) -> str:
    try:
        name = column.type.python_type.__name__
    except NotImplementedError:
        name = type(column.type).__name__
    return {"str": "text", "int": "integer", "float": "number", "Decimal": "decimal"}.get(
        name, name
    )


def schema_markdown() -> str:
    tables = list(_tables())
    lines = [
        f"{len(tables)} tables in {len(AREAS)} areas. Each diagram shows the tables of an "
        'area and the tables they refer to; `||--o{` reads "one ... has many".'
    ]
    for module, area in AREAS.items():
        mine = [t for t in tables if t[0] == module]
        if not mine:
            continue
        lines += ["", f"### {area}", "", "```mermaid", "erDiagram"]
        relations = sorted(
            {
                (fk.column.table.name, table.name, fk.parent.name)
                for _, _, table, _ in mine
                for fk in table.foreign_keys
            }
        )
        if relations:
            lines += [
                f'    {parent} ||--o{{ {child} : "{column}"' for parent, child, column in relations
            ]
        else:
            lines += [f"    {name} {{ integer id }}" for _, name, _, _ in mine]
        lines += ["```"]
        for _, name, table, doc in mine:
            lines += [
                "",
                f"#### `{name}`",
                "",
                doc,
                "",
                "| Column | Type | Required | Notes |",
                "|---|---|---|---|",
            ]
            for column in sorted(table.columns, key=lambda c: not c.primary_key):
                notes = []
                if column.primary_key:
                    notes.append("primary key")
                notes += [
                    f"→ `{fk.column.table.name}.{fk.column.name}`" for fk in column.foreign_keys
                ]
                if column.unique:
                    notes.append("unique")
                lines.append(
                    f"| `{column.name}` | {_type(column)} | {'' if column.nullable else 'yes'} "
                    f"| {', '.join(notes)} |"
                )
    return "\n".join(lines)


# -------------------------------------------------------------------------- main
def outputs() -> dict[Path, str]:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    spec = openapi()
    api_doc = DOCS / "api.md"
    db_doc = DOCS / "database.md"
    return {
        DOCS / "openapi.json": json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        api_doc: replace_section(
            api_doc.read_text(encoding="utf-8"), "endpoints", endpoints_markdown(spec)
        ),
        db_doc: replace_section(db_doc.read_text(encoding="utf-8"), "schema", schema_markdown()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the reference documentation.")
    parser.add_argument("--check", action="store_true", help="only check it is current")
    args = parser.parse_args(argv)
    stale = []
    for path, content in outputs().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != content:
            stale.append(path.relative_to(PROJECT_ROOT).as_posix())
            if not args.check:
                path.write_text(content, encoding="utf-8")
    if args.check:
        if stale:
            print(f"Out of date: {', '.join(stale)}. Run: python scripts/generate_docs.py")
            return 1
        print("The generated documentation is up to date.")
        return 0
    print(f"Updated: {', '.join(stale)}" if stale else "Already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
