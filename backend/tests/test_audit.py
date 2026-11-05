"""Tests for the audit log: automatic tracking, explicit records, immutability, API."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.catalog import Category
from app.models.user import RoleName, User
from app.services.audit_service import AuditService
from app.services.audit_tracking import set_audit_actor
from tests.factories import (
    auth_headers,
    create_bin,
    create_category,
    create_product,
    create_user,
    user_with_role,
)

API = "/api/v1"


def entries(db: Session, entity_type: str | None = None) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.id)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    return list(db.scalars(query))


@pytest.fixture()
def admin(db_session: Session) -> User:
    return user_with_role(db_session, RoleName.ADMIN)


@pytest.fixture()
def manager(db_session: Session) -> User:
    return user_with_role(db_session, RoleName.MANAGER)


# ------------------------------------------------------------ automatic tracking
def test_create_update_delete_are_recorded_with_old_and_new_values(db_session: Session):
    category = create_category(db_session, "Electronics", description="Gadgets")
    category.name = "Consumer electronics"
    category.description = None
    db_session.commit()
    db_session.delete(category)
    db_session.commit()

    created, updated, deleted = entries(db_session, "category")
    assert (created.action, created.entity_id) == ("create", category.id)
    assert created.changes["name"] == {"new": "Electronics"}
    assert created.changes["description"] == {"new": "Gadgets"}
    assert "id" not in created.changes and "created_at" not in created.changes

    assert updated.action == "update"
    assert updated.changes == {
        "name": {"old": "Electronics", "new": "Consumer electronics"},
        "description": {"old": "Gadgets", "new": None},
    }
    assert deleted.action == "delete"
    assert deleted.changes["name"] == {"old": "Consumer electronics"}
    assert all(e.actor_id is None for e in (created, updated, deleted))  # the system


def test_old_value_is_known_even_after_the_object_was_expired(db_session: Session):
    category = create_category(db_session, "Toys")
    db_session.expire(category, ["name"])  # "name" is no longer loaded

    category.name = "Games"  # set without reading it first
    db_session.commit()

    assert entries(db_session, "category")[-1].changes == {"name": {"old": "Toys", "new": "Games"}}


def test_setting_the_same_value_records_nothing(db_session: Session):
    category = create_category(db_session, "Toys")
    category.name = "Toys"
    db_session.commit()

    assert [e.action for e in entries(db_session, "category")] == ["create"]


def test_decimals_are_exact_strings(db_session: Session):
    product = create_product(db_session, create_category(db_session))
    product.unit_price = "129.90"
    db_session.commit()

    change = entries(db_session, "product")[-1].changes
    assert change == {"unit_price": {"old": "100.00", "new": "129.90"}}


def test_user_passwords_are_never_written_and_logins_are_not_noise(db_session: Session):
    user = create_user(db_session, "ann@example.com", roles=(RoleName.STAFF,))
    created = entries(db_session, "user")[-1]
    assert created.changes["hashed_password"] == {"new": "***"}
    assert created.changes["roles"] == {"new": ["staff"]}

    user.hashed_password = "something-else"
    db_session.commit()
    assert entries(db_session, "user")[-1].changes == {
        "hashed_password": {"old": "***", "new": "***"}
    }

    user.last_login_at = datetime.now(UTC)
    db_session.commit()
    assert len(entries(db_session, "user")) == 2  # last_login_at is ignored


def test_rolled_back_changes_leave_no_audit_row(db_session: Session):
    category = create_category(db_session, "Toys")
    category.name = "Games"
    db_session.flush()  # the audit row exists inside the transaction...
    db_session.rollback()  # ...and disappears with the change

    assert [e.action for e in entries(db_session, "category")] == ["create"]


def test_bulk_statements_and_inventory_are_not_tracked(db_session: Session):
    category = create_category(db_session, "Toys")
    db_session.execute(update(Category).where(Category.id == category.id).values(name="X"))
    create_bin(db_session)  # layout is tracked: warehouse, zone, rack, shelf, bin
    db_session.commit()

    assert [e.action for e in entries(db_session, "category")] == ["create"]
    assert {e.entity_type for e in entries(db_session)} == {
        "category",
        "warehouse",
        "zone",
        "rack",
        "shelf",
        "bin",
    }


# ------------------------------------------------------------ actor and API changes
def test_api_changes_are_attributed_to_the_logged_in_user(
    client: TestClient, db_session: Session, manager: User
):
    category = create_category(db_session, "Toys")
    response = client.patch(
        f"{API}/categories/{category.id}", json={"name": "Games"}, headers=auth_headers(manager)
    )
    assert response.status_code == 200

    entry = entries(db_session, "category")[-1]
    assert (entry.action, entry.actor_id, entry.actor_email) == (
        "update",
        manager.id,
        "manager@example.com",
    )
    assert entry.changes == {"name": {"old": "Toys", "new": "Games"}}


def test_role_changes_by_an_admin_are_recorded(
    client: TestClient, db_session: Session, admin: User
):
    staff = create_user(db_session, "sam@example.com", roles=(RoleName.STAFF,))

    client.patch(
        f"{API}/users/{staff.id}",
        json={"roles": ["staff", "manager"]},
        headers=auth_headers(admin),
    )

    entry = entries(db_session, "user")[-1]
    assert entry.actor_id == admin.id
    assert entry.changes == {"roles": {"old": ["staff"], "new": ["manager", "staff"]}}


# ------------------------------------------------------------ explicit records
def test_record_business_operation(db_session: Session, manager: User):
    set_audit_actor(db_session, manager)
    AuditService(db_session).record(
        "inventory.receive",
        "inventory",
        7,
        summary="Received 20 x LAP-001 into WH01-ZA-R01-S01-B01",
        changes={"quantity_on_hand": {"old": 0, "new": 20}, "when": datetime(2026, 1, 1)},
    )
    db_session.commit()

    entry = entries(db_session, "inventory")[0]
    assert (entry.action, entry.entity_id, entry.actor_id) == ("inventory.receive", 7, manager.id)
    assert entry.changes["quantity_on_hand"] == {"old": 0, "new": 20}
    assert entry.changes["when"] == "2026-01-01T00:00:00"  # made JSON-safe


def test_audit_logs_are_immutable(db_session: Session):
    create_category(db_session, "Toys")
    entry_id = entries(db_session)[0].id

    for statement in (
        update(AuditLog).filter_by(id=entry_id).values(actor_email="someone@else.com"),
        text("UPDATE audit_logs SET action = 'nothing'"),
        delete(AuditLog).filter_by(id=entry_id),
        text("DELETE FROM audit_logs"),
    ):
        with pytest.raises(IntegrityError, match="audit logs are immutable"):
            db_session.execute(statement)
        db_session.rollback()

    assert db_session.get(AuditLog, entry_id).action == "create"


# ------------------------------------------------------------ GET /audit-logs
def test_audit_log_endpoint_filters_newest_first(
    client: TestClient, db_session: Session, admin: User, manager: User
):
    headers = auth_headers(admin)
    toys = create_category(db_session, "Toys")
    create_category(db_session, "Books")
    client.patch(f"{API}/categories/{toys.id}", json={"name": "Games"}, headers=headers)

    everything = client.get(f"{API}/audit-logs", headers=headers).json()
    assert everything["items"][0]["action"] == "update"  # newest first

    toys_history = client.get(
        f"{API}/audit-logs",
        params={"entity_type": "category", "entity_id": toys.id},
        headers=headers,
    ).json()
    assert [item["action"] for item in toys_history["items"]] == ["update", "create"]
    assert toys_history["total"] == 2

    by_admin = client.get(
        f"{API}/audit-logs", params={"actor_id": admin.id, "action": "update"}, headers=headers
    ).json()
    assert by_admin["total"] == 1
    assert by_admin["items"][0]["changes"] == {"name": {"old": "Toys", "new": "Games"}}

    # Times without a timezone are taken as UTC
    future = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    later = client.get(f"{API}/audit-logs", params={"since": future}, headers=headers)
    assert later.status_code == 200
    assert later.json()["total"] == 0


@pytest.mark.parametrize("role", [RoleName.MANAGER, RoleName.STAFF, RoleName.CUSTOMER])
def test_only_admins_can_read_the_audit_log(
    client: TestClient, db_session: Session, role: RoleName
):
    user = user_with_role(db_session, role)

    assert client.get(f"{API}/audit-logs", headers=auth_headers(user)).status_code == 403
    assert client.get(f"{API}/audit-logs").status_code == 401
