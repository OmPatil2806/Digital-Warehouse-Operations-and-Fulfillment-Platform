"""Audit log responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Page


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_id: int | None  # None = the system
    actor_email: str | None
    action: str
    entity_type: str
    entity_id: int | None
    summary: str | None
    changes: dict[str, Any] | None


AuditLogPage = Page[AuditLogResponse]
