"""Automatic audit records for master data (users, catalog, warehouse layout).

Whenever the ORM writes one of the TRACKED models, an `audit_logs` row is added in the
same transaction, with the old and new value of every changed field. Services do not
have to remember to call anything, so a change can never be saved without its audit
record (and if the change is rolled back, so is its audit record).

The acting user is taken from `session.info["audit_actor"]`, which the API sets when it
authenticates a request (see `set_audit_actor`). No actor = the system.

Limits (on purpose):
- Bulk statements such as `session.execute(update(Product)...)` bypass the ORM and are
  not tracked; services use ORM objects for user-facing changes.
- Inventory and its documents are *not* tracked here: stock operations write their own,
  more meaningful records (e.g. "inventory.receive") through `AuditService.record`.
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, attributes

from app.models.audit import AuditAction, AuditLog
from app.models.catalog import Category, Product, Supplier, SupplierProduct
from app.models.user import User
from app.models.warehouse import Bin, Rack, Shelf, Warehouse, Zone

AUDIT_ACTOR_KEY = "audit_actor"

# Model -> entity_type written to the audit log.
TRACKED: dict[type, str] = {
    User: "user",
    Category: "category",
    Supplier: "supplier",
    Product: "product",
    SupplierProduct: "supplier_product",
    Warehouse: "warehouse",
    Zone: "zone",
    Rack: "rack",
    Shelf: "shelf",
    Bin: "bin",
}
# Changes of these fields are noise (or bookkeeping) and are not recorded.
IGNORED_FIELDS = {"id", "created_at", "updated_at", "last_login_at"}
# Recorded as "changed" without ever writing the value.
SECRET_FIELDS = {"hashed_password"}
HIDDEN = "***"
# Collections worth recording, with how to turn one member into a plain value.
TRACKED_COLLECTIONS: dict[type, dict[str, Callable[[Any], Any]]] = {
    User: {"roles": lambda role: role.name},
}

_installed = False


def set_audit_actor(session: Session, user: User | None) -> None:
    """Attribute every tracked change made through `session` to `user` (None = system)."""
    if user is None:
        session.info.pop(AUDIT_ACTOR_KEY, None)
    else:
        session.info[AUDIT_ACTOR_KEY] = (user.id, user.email)


def get_audit_actor(session: Session) -> tuple[int | None, str | None]:
    return session.info.get(AUDIT_ACTOR_KEY, (None, None))


def to_json_value(value: Any) -> Any:
    """Make a column value JSON-safe (exact decimals are kept as strings)."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _field_keys(model: type) -> list[str]:
    return [prop.key for prop in inspect(model).column_attrs if prop.key not in IGNORED_FIELDS]


def _snapshot(obj: object, side: str) -> dict[str, Any]:
    """All non-empty fields of a new (side="new") or deleted (side="old") object."""
    changes: dict[str, Any] = {}
    for key in _field_keys(type(obj)):
        value = getattr(obj, key)
        if value is not None:
            changes[key] = {side: HIDDEN if key in SECRET_FIELDS else to_json_value(value)}
    for key, as_value in TRACKED_COLLECTIONS.get(type(obj), {}).items():
        members = sorted(as_value(m) for m in getattr(obj, key))
        if members:
            changes[key] = {side: members}
    return changes


def _diff(obj: object) -> dict[str, Any]:
    """Fields of a modified object whose value really changed."""
    changes: dict[str, Any] = {}
    for key in _field_keys(type(obj)):
        history = attributes.get_history(obj, key)
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else None
        if old == new:
            continue
        if key in SECRET_FIELDS:
            changes[key] = {"old": HIDDEN, "new": HIDDEN}
        else:
            changes[key] = {"old": to_json_value(old), "new": to_json_value(new)}
    for key, as_value in TRACKED_COLLECTIONS.get(type(obj), {}).items():
        history = attributes.get_history(obj, key)
        if not history.has_changes():
            continue
        old = sorted(as_value(m) for m in [*history.unchanged, *history.deleted])
        new = sorted(as_value(m) for m in [*history.unchanged, *history.added])
        if old != new:
            changes[key] = {"old": old, "new": new}
    return changes


def _before_flush(session: Session, _flush_context: object, _instances: object) -> None:
    """Collect what is about to change (old values are still known before the flush)."""
    pending = session.info.setdefault("_audit_pending", [])
    for obj in session.dirty:
        if type(obj) in TRACKED and session.is_modified(obj):
            changes = _diff(obj)
            if changes:
                pending.append((AuditAction.UPDATE, obj, changes))
    for obj in session.deleted:
        if type(obj) in TRACKED:
            pending.append((AuditAction.DELETE, obj, _snapshot(obj, "old")))
    for obj in session.new:
        if type(obj) in TRACKED:
            pending.append((AuditAction.CREATE, obj, None))  # id/defaults known after flush


def _after_flush(session: Session, _flush_context: object) -> None:
    """Write the collected audit rows in the same transaction as the changes."""
    pending = session.info.pop("_audit_pending", [])
    if not pending:
        return
    actor_id, actor_email = get_audit_actor(session)
    rows = []
    for action, obj, changes in pending:
        rows.append(
            {
                "actor_id": actor_id,
                "actor_email": actor_email,
                "action": action.value,
                "entity_type": TRACKED[type(obj)],
                "entity_id": obj.id,
                "changes": changes if changes is not None else _snapshot(obj, "new"),
            }
        )
    session.connection().execute(AuditLog.__table__.insert(), rows)


def _after_rollback(session: Session) -> None:
    session.info.pop("_audit_pending", None)


def install_audit_tracking() -> None:
    """Register the listeners (once per process; called when `app.models` is imported)."""
    global _installed
    if _installed:
        return
    # active_history: load the old value before a change, even if the attribute was
    # expired, so "old" is always known.
    for model in TRACKED:
        for key in _field_keys(model):
            event.listen(getattr(model, key), "set", _ignore, active_history=True)
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_soft_rollback", lambda session, _tx: _after_rollback(session))
    _installed = True


def _ignore(*_args: object) -> None:
    """The "set" listener only exists to switch on active_history."""
