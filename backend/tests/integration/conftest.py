"""Shared set-up of the end-to-end business scenarios.

Each scenario drives the platform only through its HTTP API, the way the web app does,
with the role that does the work in a real warehouse: a manager plans, staff pick, pack
and ship, a customer follows their own order. Every scenario starts from an empty,
migrated database (rolled back afterwards, see tests/conftest.py).
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import RoleName
from tests.factories import (
    auth_headers,
    create_bin,
    create_carrier,
    create_category,
    create_customer,
    create_product,
    create_user,
)


@dataclass
class Warehouse:
    """A small warehouse with people, two products, bins, a customer and a carrier."""

    manager: dict[str, str]
    staff: dict[str, str]
    customer: dict[str, str]
    customer_id: int
    laptop: int
    mouse: int
    pick_bin: int
    returns_bin: int
    carrier: int


@pytest.fixture()
def warehouse(db_session: Session) -> Warehouse:
    db = db_session
    category = create_category(db)
    laptop = create_product(db, category, sku="LAP-001", name="Laptop")
    mouse = create_product(db, category, sku="MOU-001", name="Mouse")
    pick_bin = create_bin(db, "WH01-ZA-R01-S01-B01")
    returns_bin = create_bin(db, "WH01-ZA-R01-S01-B02")
    manager = create_user(db, "maya@example.com", roles=(RoleName.MANAGER,))
    staff = create_user(db, "sam@example.com", roles=(RoleName.STAFF,))
    buyer = create_user(db, "chris@example.com", roles=(RoleName.CUSTOMER,))
    customer = create_customer(db, user_id=buyer.id)
    return Warehouse(
        manager=auth_headers(manager),
        staff=auth_headers(staff),
        customer=auth_headers(buyer),
        customer_id=customer.id,
        laptop=laptop.id,
        mouse=mouse.id,
        pick_bin=pick_bin.id,
        returns_bin=returns_bin.id,
        carrier=create_carrier(db, "DHL", default_transit_days=2).id,
    )


def ok(response, status: int = 200) -> dict:
    """The JSON body of a response, failing with the API's message if the status differs."""
    assert response.status_code == status, response.text
    return response.json()


def stock(client: TestClient, headers: dict[str, str], product_id: int) -> dict:
    """On-hand, reserved and available units of a product over all bins."""
    rows = ok(client.get("/api/v1/inventory", params={"product_id": product_id}, headers=headers))
    items = rows["items"]
    return {
        key: sum(int(row[key]) for row in items)
        for key in ("quantity_on_hand", "quantity_reserved", "quantity_available")
    }
