"""HTTP tests for /api/v1/suppliers and supplier-product links."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import RoleName
from tests.factories import (
    auth_headers,
    create_category,
    create_product,
    create_supplier,
    user_with_role,
)

SUPPLIERS = "/api/v1/suppliers"
NEW_SUPPLIER = {
    "code": "sup-100",
    "name": "Acme Parts GmbH",
    "email": "Sales@Acme.example",
    "country": "Germany",
    "lead_time_days": 5,
    "reliability_score": "0.92",
}


@pytest.fixture()
def manager(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.MANAGER))


@pytest.fixture()
def staff(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.STAFF))


# ------------------------------------------------------------------------ suppliers


def test_create_supplier(client: TestClient, manager: dict) -> None:
    response = client.post(SUPPLIERS, json=NEW_SUPPLIER, headers=manager)

    body = response.json()
    assert response.status_code == 201
    assert body["code"] == "SUP-100"
    assert body["reliability_score"] == "0.92"
    assert body["lead_time_days"] == 5
    assert body["is_active"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "a"},
        {"code": "has space"},
        {"email": "not-an-email"},
        {"lead_time_days": -1},
        {"lead_time_days": 400},
        {"reliability_score": "1.5"},
        {"reliability_score": "0.925"},
    ],
)
def test_invalid_supplier_is_422(client: TestClient, manager: dict, overrides: dict) -> None:
    response = client.post(SUPPLIERS, json={**NEW_SUPPLIER, **overrides}, headers=manager)

    assert response.status_code == 422


def test_duplicate_code_is_409(client: TestClient, manager: dict) -> None:
    client.post(SUPPLIERS, json=NEW_SUPPLIER, headers=manager)

    response = client.post(
        SUPPLIERS, json={**NEW_SUPPLIER, "code": "SUP-100", "name": "Other"}, headers=manager
    )

    assert response.status_code == 409


def test_search_filter_sort(client: TestClient, db_session: Session, staff: dict) -> None:
    create_supplier(db_session, "SUP-001", name="Zeta Logistics", country="Poland")
    create_supplier(db_session, "SUP-002", name="Alpha Tools", lead_time_days=2)
    create_supplier(db_session, "SUP-003", name="Old Co", is_active=False, lead_time_days=30)

    def codes(query: str) -> list[str]:
        return [
            s["code"] for s in client.get(f"{SUPPLIERS}?{query}", headers=staff).json()["items"]
        ]

    assert codes("") == ["SUP-001", "SUP-002", "SUP-003"]
    assert codes("q=poland") == ["SUP-001"]
    assert codes("q=alpha") == ["SUP-002"]
    assert codes("is_active=true") == ["SUP-001", "SUP-002"]
    assert codes("sort=-lead_time_days") == ["SUP-003", "SUP-001", "SUP-002"]
    assert codes("sort=name") == ["SUP-002", "SUP-003", "SUP-001"]


def test_update_clear_contact_and_archive(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    supplier = create_supplier(db_session, "SUP-001", email="a@example.com")

    response = client.patch(
        f"{SUPPLIERS}/{supplier.id}",
        json={"email": None, "lead_time_days": 12, "is_active": False},
        headers=manager,
    )

    body = response.json()
    assert body["email"] is None
    assert body["lead_time_days"] == 12
    assert body["is_active"] is False
    assert body["name"] == "Supplier SUP-001"  # required field untouched


def test_permissions(client: TestClient, db_session: Session, staff: dict) -> None:
    supplier = create_supplier(db_session, "SUP-001")
    customer = auth_headers(user_with_role(db_session, RoleName.CUSTOMER))

    assert client.get(SUPPLIERS, headers=staff).status_code == 200  # staff may read
    assert client.post(SUPPLIERS, json=NEW_SUPPLIER, headers=staff).status_code == 403
    assert client.patch(f"{SUPPLIERS}/{supplier.id}", json={}, headers=staff).status_code == 403
    assert client.get(SUPPLIERS, headers=customer).status_code == 403  # internal data
    assert client.get(f"{SUPPLIERS}/{supplier.id}", headers=customer).status_code == 403


def test_unknown_supplier_is_404(client: TestClient, staff: dict) -> None:
    assert client.get(f"{SUPPLIERS}/999999", headers=staff).status_code == 404


# --------------------------------------------------------------- supplier products


@pytest.fixture()
def setup(db_session: Session):  # noqa: ANN201
    category = create_category(db_session)
    return {
        "supplier": create_supplier(db_session, "SUP-001", lead_time_days=10),
        "other_supplier": create_supplier(db_session, "SUP-002"),
        "product": create_product(db_session, category, "LAP-001"),
        "second_product": create_product(db_session, category, "MOU-001"),
    }


def link_url(supplier_id: int, product_id: int | None = None) -> str:
    base = f"{SUPPLIERS}/{supplier_id}/products"
    return base if product_id is None else f"{base}/{product_id}"


def test_add_and_list_supplier_products(client: TestClient, manager: dict, setup) -> None:
    supplier, product = setup["supplier"], setup["product"]

    created = client.post(
        link_url(supplier.id),
        json={"product_id": product.id, "supplier_sku": "AC-9", "unit_cost": "640.00"},
        headers=manager,
    )
    listed = client.get(link_url(supplier.id), headers=manager)

    body = created.json()
    assert created.status_code == 201
    assert body["product"] == {"id": product.id, "name": "Product LAP-001", "sku": "LAP-001"}
    assert body["supplier"]["code"] == "SUP-001"
    assert body["unit_cost"] == "640.00"
    assert body["lead_time_days"] is None
    assert body["effective_lead_time_days"] == 10  # inherited from the supplier
    assert body["min_order_qty"] == 1
    assert [link["product"]["sku"] for link in listed.json()] == ["LAP-001"]


def test_duplicate_link_is_409_and_bad_references_are_422(
    client: TestClient, db_session: Session, manager: dict, setup
) -> None:
    supplier, product = setup["supplier"], setup["product"]
    body = {"product_id": product.id, "unit_cost": "1.00"}
    client.post(link_url(supplier.id), json=body, headers=manager)
    archived = create_supplier(db_session, "SUP-OLD", is_active=False)

    duplicate = client.post(link_url(supplier.id), json=body, headers=manager)
    missing_product = client.post(
        link_url(supplier.id), json={"product_id": 999999, "unit_cost": "1"}, headers=manager
    )
    archived_supplier = client.post(link_url(archived.id), json=body, headers=manager)
    missing_supplier = client.post(link_url(999999), json=body, headers=manager)

    assert duplicate.status_code == 409
    assert missing_product.status_code == 422
    assert archived_supplier.status_code == 422
    assert missing_supplier.status_code == 404


def test_only_one_preferred_supplier_per_product(client: TestClient, manager: dict, setup) -> None:
    product = setup["product"]
    for supplier in (setup["supplier"], setup["other_supplier"]):
        client.post(
            link_url(supplier.id),
            json={"product_id": product.id, "unit_cost": "5", "is_preferred": True},
            headers=manager,
        )

    offers = client.get(f"/api/v1/products/{product.id}/suppliers", headers=manager).json()

    preferred = [offer["supplier"]["code"] for offer in offers if offer["is_preferred"]]
    assert preferred == ["SUP-002"]  # the latest choice wins
    assert offers[0]["is_preferred"] is True  # preferred offer listed first

    client.patch(
        link_url(setup["supplier"].id, product.id), json={"is_preferred": True}, headers=manager
    )
    offers = client.get(f"/api/v1/products/{product.id}/suppliers", headers=manager).json()
    assert [o["supplier"]["code"] for o in offers if o["is_preferred"]] == ["SUP-001"]


def test_update_and_remove_link(client: TestClient, manager: dict, setup) -> None:
    supplier, product = setup["supplier"], setup["product"]
    client.post(
        link_url(supplier.id),
        json={"product_id": product.id, "unit_cost": "5", "lead_time_days": 3},
        headers=manager,
    )

    updated = client.patch(
        link_url(supplier.id, product.id),
        json={"unit_cost": "4.50", "lead_time_days": None, "min_order_qty": 10},
        headers=manager,
    )
    removed = client.delete(link_url(supplier.id, product.id), headers=manager)
    missing = client.delete(link_url(supplier.id, product.id), headers=manager)

    assert updated.json()["unit_cost"] == "4.50"
    assert updated.json()["effective_lead_time_days"] == 10  # override cleared
    assert updated.json()["min_order_qty"] == 10
    assert removed.status_code == 204
    assert missing.status_code == 404


def test_supplier_filter_on_products_uses_links(client: TestClient, manager: dict, setup) -> None:
    client.post(
        link_url(setup["supplier"].id),
        json={"product_id": setup["second_product"].id, "unit_cost": "2"},
        headers=manager,
    )

    page = client.get(f"/api/v1/products?supplier_id={setup['supplier'].id}", headers=manager)

    assert [p["sku"] for p in page.json()["items"]] == ["MOU-001"]


def test_staff_reads_links_but_cannot_change_them(client: TestClient, staff: dict, setup) -> None:
    supplier, product = setup["supplier"], setup["product"]

    assert client.get(link_url(supplier.id), headers=staff).status_code == 200
    assert (
        client.post(
            link_url(supplier.id), json={"product_id": product.id, "unit_cost": "1"}, headers=staff
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/products/{product.id}/suppliers", headers=staff).status_code == 200


def test_reliability_decimal_round_trip(
    client: TestClient, db_session: Session, staff: dict
) -> None:
    supplier = create_supplier(db_session, "SUP-009", reliability_score=Decimal("0.80"))

    assert client.get(f"{SUPPLIERS}/{supplier.id}", headers=staff).json()["reliability_score"] == (
        "0.80"
    )
