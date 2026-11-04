"""HTTP tests for /api/v1/products."""

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

PRODUCTS = "/api/v1/products"


@pytest.fixture()
def manager(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.MANAGER))


@pytest.fixture()
def category(db_session: Session):  # noqa: ANN201
    return create_category(db_session, "Electronics")


def new_product(category_id: int, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "sku": "lap-001",
        "name": "  Laptop 14 inch ",
        "category_id": category_id,
        "brand": "Acme",
        "unit_price": "899.99",
        "unit_cost": 650,
        "weight_kg": 1.45,
        "length_cm": "33.0",
        "width_cm": 23.5,
        "height_cm": 2,
        "barcode": "4006381333931",
        "min_stock": 5,
        "max_stock": 50,
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------------------- create


def test_manager_creates_product_with_exact_decimals(
    client: TestClient, manager: dict, category
) -> None:
    response = client.post(PRODUCTS, json=new_product(category.id), headers=manager)

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "LAP-001"  # normalised to upper case
    assert body["name"] == "Laptop 14 inch"  # trimmed
    assert body["unit_price"] == "899.99"  # decimals are exact strings
    assert body["unit_cost"] == "650.00"
    assert body["weight_kg"] == "1.450"
    assert body["margin"] == "249.99"
    assert body["volume_cm3"] == "1551.000"
    assert body["category"] == {"id": category.id, "name": "Electronics"}
    assert body["default_supplier"] is None
    assert body["is_active"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"sku": "x"},  # too short
        {"sku": "has space"},
        {"unit_price": "-1"},
        {"unit_price": "1.999"},  # too many decimal places
        {"weight_kg": 0},
        {"length_cm": "-5"},
        {"barcode": "12345"},
        {"min_stock": 10, "max_stock": 5},
        {"name": "   "},
    ],
)
def test_invalid_product_is_422(
    client: TestClient, manager: dict, category, overrides: dict
) -> None:
    response = client.post(PRODUCTS, json=new_product(category.id, **overrides), headers=manager)

    assert response.status_code == 422


def test_duplicate_sku_is_409_case_insensitive(client: TestClient, manager: dict, category) -> None:
    client.post(PRODUCTS, json=new_product(category.id), headers=manager)

    response = client.post(
        PRODUCTS, json=new_product(category.id, sku="LAP-001", barcode=None), headers=manager
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "A product with this SKU already exists"}


def test_duplicate_barcode_is_409(client: TestClient, manager: dict, category) -> None:
    client.post(PRODUCTS, json=new_product(category.id), headers=manager)

    response = client.post(PRODUCTS, json=new_product(category.id, sku="OTHER-1"), headers=manager)

    assert response.status_code == 409
    assert response.json() == {"detail": "A product with this barcode already exists"}


def test_missing_or_archived_category_is_422(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    archived = create_category(db_session, "Old", is_active=False)

    missing = client.post(PRODUCTS, json=new_product(999_999), headers=manager)
    old = client.post(PRODUCTS, json=new_product(archived.id), headers=manager)

    assert (missing.status_code, missing.json()["detail"]) == (422, "Category not found")
    assert (old.status_code, old.json()["detail"]) == (422, "Category is archived")


def test_default_supplier_is_validated(
    client: TestClient, db_session: Session, manager: dict, category
) -> None:
    supplier = create_supplier(db_session, "SUP-001")
    archived = create_supplier(db_session, "SUP-OLD", is_active=False)

    ok = client.post(
        PRODUCTS, json=new_product(category.id, default_supplier_id=supplier.id), headers=manager
    )
    bad = client.post(
        PRODUCTS,
        json=new_product(category.id, sku="B-1", barcode=None, default_supplier_id=archived.id),
        headers=manager,
    )

    assert ok.json()["default_supplier"] == {
        "id": supplier.id,
        "name": "Supplier SUP-001",
        "code": "SUP-001",
    }
    assert (bad.status_code, bad.json()["detail"]) == (422, "Default supplier is archived")


# ---------------------------------------------------------------------- list/search


@pytest.fixture()
def catalog(db_session: Session):  # noqa: ANN201
    electronics = create_category(db_session, "Electronics")
    laptops = create_category(db_session, "Laptops", parent_id=electronics.id)
    tools = create_category(db_session, "Tools")
    supplier = create_supplier(db_session, "SUP-001")
    create_product(db_session, laptops, "LAP-001", name="Laptop Pro", unit_price=Decimal("999.00"))
    create_product(
        db_session,
        electronics,
        "MOU-001",
        name="Mouse",
        brand="Clicky",
        unit_price=Decimal("19.99"),
        default_supplier_id=supplier.id,
    )
    create_product(
        db_session, tools, "DRL-001", name="Drill", unit_price=Decimal("149.50"), barcode="12345678"
    )
    create_product(db_session, tools, "OLD-001", name="Old hammer", is_active=False)
    return {"electronics": electronics, "laptops": laptops, "tools": tools, "supplier": supplier}


def skus(response) -> list[str]:  # noqa: ANN001
    return [item["sku"] for item in response.json()["items"]]


def test_list_is_sorted_by_sku_and_paginated(client: TestClient, manager: dict, catalog) -> None:
    first = client.get(f"{PRODUCTS}?limit=2", headers=manager)
    second = client.get(f"{PRODUCTS}?limit=2&offset=2", headers=manager)

    assert first.json()["total"] == 4
    assert skus(first) == ["DRL-001", "LAP-001"]
    assert skus(second) == ["MOU-001", "OLD-001"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("q=laptop", ["LAP-001"]),  # name, case-insensitive
        ("q=mou", ["MOU-001"]),  # SKU
        ("q=clicky", ["MOU-001"]),  # brand
        ("q=12345678", ["DRL-001"]),  # barcode
        ("q=%25", []),  # a literal "%" is not a wildcard
        ("is_active=false", ["OLD-001"]),
        ("sort=-unit_price", ["LAP-001", "DRL-001", "OLD-001", "MOU-001"]),
        ("sort=name", ["DRL-001", "LAP-001", "MOU-001", "OLD-001"]),
    ],
)
def test_search_filters_and_sorting(
    client: TestClient, manager: dict, catalog, query: str, expected: list[str]
) -> None:
    assert skus(client.get(f"{PRODUCTS}?{query}", headers=manager)) == expected


def test_category_filter_includes_sub_categories(
    client: TestClient, manager: dict, catalog
) -> None:
    electronics = catalog["electronics"].id

    response = client.get(f"{PRODUCTS}?category_id={electronics}", headers=manager)

    assert skus(response) == ["LAP-001", "MOU-001"]  # LAP-001 is in the "Laptops" sub-category


def test_supplier_filter(client: TestClient, manager: dict, catalog) -> None:
    response = client.get(f"{PRODUCTS}?supplier_id={catalog['supplier'].id}", headers=manager)

    assert skus(response) == ["MOU-001"]


@pytest.mark.parametrize("query", ["sort=price", "limit=0", "limit=101", "offset=-1"])
def test_invalid_list_parameters_are_422(client: TestClient, manager: dict, query: str) -> None:
    assert client.get(f"{PRODUCTS}?{query}", headers=manager).status_code == 422


def test_unknown_category_filter_is_404(client: TestClient, manager: dict) -> None:
    assert client.get(f"{PRODUCTS}?category_id=999999", headers=manager).status_code == 404


# ------------------------------------------------------------------------- update


def test_patch_changes_only_sent_fields_and_can_clear_optional_ones(
    client: TestClient, db_session: Session, manager: dict, category
) -> None:
    product = create_product(db_session, category, "UPD-001", brand="Old", barcode="12345678")

    response = client.patch(
        f"{PRODUCTS}/{product.id}",
        json={"unit_price": "120.50", "brand": None, "barcode": None},
        headers=manager,
    )

    body = response.json()
    assert response.status_code == 200
    assert body["unit_price"] == "120.50"
    assert body["brand"] is None
    assert body["barcode"] is None
    assert body["name"] == "Product UPD-001"  # unchanged


def test_patch_checks_stock_levels_against_stored_values(
    client: TestClient, db_session: Session, manager: dict, category
) -> None:
    product = create_product(db_session, category, "STK-001", min_stock=10, max_stock=20)

    response = client.patch(f"{PRODUCTS}/{product.id}", json={"max_stock": 5}, headers=manager)

    assert response.status_code == 422
    assert response.json()["detail"] == "max_stock must be greater than or equal to min_stock"


def test_patch_to_existing_sku_is_409(
    client: TestClient, db_session: Session, manager: dict, category
) -> None:
    create_product(db_session, category, "AAA-001")
    other = create_product(db_session, category, "BBB-001")

    response = client.patch(f"{PRODUCTS}/{other.id}", json={"sku": "aaa-001"}, headers=manager)

    assert response.status_code == 409


def test_archive_and_restore(
    client: TestClient, db_session: Session, manager: dict, category
) -> None:
    product = create_product(db_session, category, "ARC-001")

    archived = client.patch(f"{PRODUCTS}/{product.id}", json={"is_active": False}, headers=manager)
    restored = client.patch(f"{PRODUCTS}/{product.id}", json={"is_active": True}, headers=manager)

    assert archived.json()["is_active"] is False
    assert restored.json()["is_active"] is True


def test_cannot_restore_product_in_archived_category(
    client: TestClient, db_session: Session, manager: dict
) -> None:
    old_category = create_category(db_session, "Discontinued", is_active=False)
    product = create_product(db_session, old_category, "DIS-001", is_active=False)

    response = client.patch(f"{PRODUCTS}/{product.id}", json={"is_active": True}, headers=manager)

    assert response.status_code == 422


def test_get_unknown_product_is_404(client: TestClient, manager: dict) -> None:
    assert client.get(f"{PRODUCTS}/999999", headers=manager).status_code == 404


# ------------------------------------------------------------------------ permissions


@pytest.mark.parametrize("role", [RoleName.STAFF, RoleName.CUSTOMER])
def test_only_managers_and_admins_can_change_products(
    client: TestClient, db_session: Session, category, role: RoleName
) -> None:
    headers = auth_headers(user_with_role(db_session, role))
    product = create_product(db_session, category, "PRM-001")

    created = client.post(PRODUCTS, json=new_product(category.id), headers=headers)
    updated = client.patch(f"{PRODUCTS}/{product.id}", json={"name": "X"}, headers=headers)

    assert (created.status_code, updated.status_code) == (403, 403)


def test_admin_can_change_products(client: TestClient, db_session: Session, category) -> None:
    admin = auth_headers(user_with_role(db_session, RoleName.ADMIN))

    assert client.post(PRODUCTS, json=new_product(category.id), headers=admin).status_code == 201


def test_staff_sees_full_data_including_archived(
    client: TestClient, db_session: Session, catalog
) -> None:
    staff = auth_headers(user_with_role(db_session, RoleName.STAFF))

    response = client.get(PRODUCTS, headers=staff)

    assert response.json()["total"] == 4
    assert "unit_cost" in response.json()["items"][0]


def test_customers_see_only_active_products_without_costs(
    client: TestClient, db_session: Session, catalog
) -> None:
    customer = auth_headers(user_with_role(db_session, RoleName.CUSTOMER))

    page = client.get(f"{PRODUCTS}?is_active=false", headers=customer).json()

    assert [item["sku"] for item in page["items"]] == ["DRL-001", "LAP-001", "MOU-001"]
    for hidden in ("unit_cost", "margin", "min_stock", "max_stock", "default_supplier"):
        assert hidden not in page["items"][0]
    assert page["items"][0]["unit_price"] == "149.50"


def test_customer_gets_404_for_archived_product_and_ignores_supplier_filter(
    client: TestClient, db_session: Session, catalog
) -> None:
    customer = auth_headers(user_with_role(db_session, RoleName.CUSTOMER))
    archived_id = client.get(
        f"{PRODUCTS}?q=OLD-001",
        headers=auth_headers(user_with_role(db_session, RoleName.MANAGER)),
    ).json()["items"][0]["id"]

    assert client.get(f"{PRODUCTS}/{archived_id}", headers=customer).status_code == 404
    supplier_filtered = client.get(
        f"{PRODUCTS}?supplier_id={catalog['supplier'].id}", headers=customer
    ).json()
    assert supplier_filtered["total"] == 3  # filter ignored, not leaked


def test_anonymous_gets_401(client: TestClient) -> None:
    assert client.get(PRODUCTS).status_code == 401
