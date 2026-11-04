"""HTTP tests for /api/v1/categories."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import RoleName
from tests.factories import auth_headers, create_category, create_product, user_with_role

CATEGORIES = "/api/v1/categories"


@pytest.fixture()
def manager(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.MANAGER))


def test_create_and_list_with_product_counts(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    created = client.post(
        CATEGORIES, json={"name": " Electronics ", "description": "Gadgets"}, headers=manager
    )
    category_id = created.json()["id"]
    create_product(db_session, db_session.get(type_of_category(), category_id), "A-1")
    create_product(db_session, db_session.get(type_of_category(), category_id), "A-2")
    create_product(
        db_session, db_session.get(type_of_category(), category_id), "A-3", is_active=False
    )

    page = client.get(CATEGORIES, headers=manager).json()

    assert created.status_code == 201
    assert created.json()["name"] == "Electronics"
    assert page["total"] == 1
    assert page["items"][0]["product_count"] == 2  # only active products are counted


def type_of_category():  # noqa: ANN201
    from app.models.catalog import Category

    return Category


def test_duplicate_name_is_409_case_insensitive(client: TestClient, manager: dict) -> None:
    client.post(CATEGORIES, json={"name": "Tools"}, headers=manager)

    response = client.post(CATEGORIES, json={"name": "tools"}, headers=manager)

    assert response.status_code == 409


def test_sub_category_and_parent_validation(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    parent = create_category(db_session, "Electronics")
    archived = create_category(db_session, "Old", is_active=False)

    child = client.post(
        CATEGORIES, json={"name": "Laptops", "parent_id": parent.id}, headers=manager
    )
    missing = client.post(CATEGORIES, json={"name": "X", "parent_id": 999999}, headers=manager)
    under_archived = client.post(
        CATEGORIES, json={"name": "Y", "parent_id": archived.id}, headers=manager
    )

    assert child.json()["parent_id"] == parent.id
    assert (missing.status_code, missing.json()["detail"]) == (422, "Parent category not found")
    assert (under_archived.status_code, under_archived.json()["detail"]) == (
        422,
        "Parent category is archived",
    )
    children = client.get(f"{CATEGORIES}?parent_id={parent.id}", headers=manager).json()
    assert [c["name"] for c in children["items"]] == ["Laptops"]


def test_category_cannot_be_moved_into_its_own_subtree(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    top = create_category(db_session, "Top")
    middle = create_category(db_session, "Middle", parent_id=top.id)
    bottom = create_category(db_session, "Bottom", parent_id=middle.id)

    into_self = client.patch(f"{CATEGORIES}/{top.id}", json={"parent_id": top.id}, headers=manager)
    into_grandchild = client.patch(
        f"{CATEGORIES}/{top.id}", json={"parent_id": bottom.id}, headers=manager
    )
    to_root = client.patch(f"{CATEGORIES}/{bottom.id}", json={"parent_id": None}, headers=manager)

    assert into_self.status_code == 422
    assert into_grandchild.status_code == 422
    assert to_root.status_code == 200 and to_root.json()["parent_id"] is None


def test_archive_rules(client: TestClient, db_session: Session, manager: dict) -> None:
    with_product = create_category(db_session, "HasProducts")
    create_product(db_session, with_product, "P-1")
    parent = create_category(db_session, "Parent")
    create_category(db_session, "Child", parent_id=parent.id)
    empty = create_category(db_session, "Empty")

    blocked_products = client.patch(
        f"{CATEGORIES}/{with_product.id}", json={"is_active": False}, headers=manager
    )
    blocked_children = client.patch(
        f"{CATEGORIES}/{parent.id}", json={"is_active": False}, headers=manager
    )
    ok = client.patch(f"{CATEGORIES}/{empty.id}", json={"is_active": False}, headers=manager)

    assert blocked_products.status_code == 409
    assert blocked_children.status_code == 409
    assert ok.status_code == 200 and ok.json()["is_active"] is False


def test_child_cannot_be_restored_under_archived_parent(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    parent = create_category(db_session, "Parent", is_active=False)
    child = create_category(db_session, "Child", parent_id=parent.id, is_active=False)

    response = client.patch(f"{CATEGORIES}/{child.id}", json={"is_active": True}, headers=manager)

    assert response.status_code == 422


def test_customers_only_see_active_categories(client: TestClient, db_session: Session) -> None:
    create_category(db_session, "Visible")
    hidden = create_category(db_session, "Hidden", is_active=False)
    customer = auth_headers(user_with_role(db_session, RoleName.CUSTOMER))

    page = client.get(f"{CATEGORIES}?is_active=false", headers=customer).json()

    assert [c["name"] for c in page["items"]] == ["Visible"]
    assert client.get(f"{CATEGORIES}/{hidden.id}", headers=customer).status_code == 404


@pytest.mark.parametrize("role", [RoleName.STAFF, RoleName.CUSTOMER])
def test_only_managers_and_admins_can_change_categories(
    client: TestClient, db_session: Session, role: RoleName
) -> None:
    headers = auth_headers(user_with_role(db_session, role))
    category = create_category(db_session, "Existing")

    assert client.post(CATEGORIES, json={"name": "New"}, headers=headers).status_code == 403
    assert (
        client.patch(f"{CATEGORIES}/{category.id}", json={"name": "X"}, headers=headers).status_code
        == 403
    )
