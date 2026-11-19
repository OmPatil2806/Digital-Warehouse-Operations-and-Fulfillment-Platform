"""Tests for the customer endpoints (/api/v1/customers) and customer logins."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import RoleName
from tests.factories import auth_headers, create_customer, create_user

API = "/api/v1/customers"


def headers(db: Session, email: str, role: RoleName) -> tuple[dict[str, str], int]:
    user = create_user(db, email, roles=(role,))
    return auth_headers(user), user.id


def test_managers_create_customers_with_the_next_code(client: TestClient, db_session: Session):
    manager, _ = headers(db_session, "maya@example.com", RoleName.MANAGER)
    first = client.post(API, json={"name": "Alpha GmbH"}, headers=manager)
    second = client.post(
        API, json={"name": "Beta AG", "customer_type": "business"}, headers=manager
    )
    assert first.status_code == second.status_code == 201
    assert (first.json()["code"], second.json()["code"]) == ("CUST-0001", "CUST-0002")
    duplicate = client.post(API, json={"code": "cust-0001", "name": "Copy"}, headers=manager)
    assert duplicate.status_code == 409  # codes are unique (stored upper-case)


def test_only_managers_change_customers(client: TestClient, db_session: Session):
    staff, _ = headers(db_session, "sam@example.com", RoleName.STAFF)
    customer = create_customer(db_session)
    assert client.get(f"{API}/{customer.id}", headers=staff).status_code == 200
    assert client.post(API, json={"name": "X Ltd"}, headers=staff).status_code == 403
    assert (
        client.patch(f"{API}/{customer.id}", json={"name": "Y"}, headers=staff).status_code == 403
    )
    buyer, _ = headers(db_session, "chris@example.com", RoleName.CUSTOMER)
    assert client.get(API, headers=buyer).status_code == 403


def test_unknown_customer_is_not_found(client: TestClient, db_session: Session):
    manager, _ = headers(db_session, "maya@example.com", RoleName.MANAGER)
    assert client.get(f"{API}/999", headers=manager).status_code == 404
    assert client.patch(f"{API}/999", json={"name": "Nobody"}, headers=manager).status_code == 404


def test_linking_a_login(client: TestClient, db_session: Session):
    manager, _ = headers(db_session, "maya@example.com", RoleName.MANAGER)
    buyer, buyer_id = headers(db_session, "chris@example.com", RoleName.CUSTOMER)
    _, staff_id = headers(db_session, "sam@example.com", RoleName.STAFF)
    first = create_customer(db_session, "CUST-0001")
    second = create_customer(db_session, "CUST-0002")

    # Before linking, the login has no customer and may not see orders.
    assert client.get(f"{API}/me", headers=buyer).status_code == 404
    assert client.get("/api/v1/orders", headers=buyer).status_code == 403

    def link(customer_id: int, user_id: int | None):
        return client.patch(f"{API}/{customer_id}", json={"user_id": user_id}, headers=manager)

    assert link(first.id, 999).status_code == 422  # no such user
    assert link(first.id, staff_id).status_code == 422  # not a customer login
    assert link(first.id, buyer_id).status_code == 200
    assert client.get(f"{API}/me", headers=buyer).json()["code"] == "CUST-0001"
    assert client.get("/api/v1/orders", headers=buyer).status_code == 200
    conflict = link(second.id, buyer_id)  # one login, one customer
    assert conflict.status_code == 409 and "CUST-0001" in conflict.json()["detail"]
    assert link(first.id, buyer_id).status_code == 200  # re-saving the same link is fine

    # Unlinking (null) is allowed; so is clearing the e-mail, while a null name is ignored.
    body = client.patch(
        f"{API}/{first.id}",
        json={"user_id": None, "email": None, "name": None},
        headers=manager,
    ).json()
    assert body["user_id"] is None and body["email"] is None and body["name"] == first.name

    # A deactivated customer's login is locked out of orders again.
    link(first.id, buyer_id)
    client.patch(f"{API}/{first.id}", json={"is_active": False}, headers=manager)
    assert client.get("/api/v1/orders", headers=buyer).status_code == 403
