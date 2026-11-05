"""The audit log: who changed what, when, with old and new values.

Two ways rows get written:

1. Automatically for users, catalog and warehouse layout (see `audit_tracking.py`):
   every ORM change of those models is recorded as create / update / delete.
2. Explicitly by business operations through `AuditService.record`, e.g.
   `record("inventory.receive", "inventory", row.id, summary="Received 20 x LAP-001")`.
   The row is added to the current transaction, so it is saved together with the
   operation (and rolled back with it).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.repositories.audit_repository import AuditRepository
from app.services.audit_tracking import get_audit_actor, to_json_value


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.entries = AuditRepository(db)

    def record(
        self,
        action: str,
        entity_type: str,
        entity_id: int | None,
        *,
        summary: str | None = None,
        changes: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Add an audit row for a business operation (the caller commits)."""
        actor_id, actor_email = get_audit_actor(self.db)
        return self.entries.add(
            AuditLog(
                actor_id=actor_id,
                actor_email=actor_email,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                changes=_json_safe(changes),
            )
        )

    def search(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        entity_type: str | None = None,
        entity_id: int | None = None,
        actor_id: int | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Sequence[AuditLog], int]:
        return self.entries.search(
            offset=offset,
            limit=limit,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
            since=since,
            until=until,
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    return to_json_value(value)
