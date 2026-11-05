"""HTTP tests for the warehouse layout API."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import RoleName
from app.models.warehouse import Bin, Rack, Shelf
from tests.factories import (
    auth_headers,
    create_category,
    create_product,
    user_with_role,
)

API = "/api/v1"


@pytest.fixture()
def manager(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.MANAGER))


@pytest.fixture()
def staff(db_session: Session) -> dict[str, str]:
    return auth_headers(user_with_role(db_session, RoleName.STAFF))


def post(client: TestClient, url: str, body: dict, headers: dict) -> dict:
    response = client.post(f"{API}{url}", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def zone(client: TestClient, manager: dict) -> dict:
    warehouse = post(client, "/warehouses", {"code": "wh01", "name": "Main"}, manager)
    return post(
        client,
        f"/warehouses/{warehouse['id']}/zones",
        {"code": "za", "name": "Picking A", "zone_type": "picking"},
        manager,
    )


GENERATE = {
    "racks": 3,
    "shelves_per_rack": 2,
    "bins_per_shelf": 4,
    "max_weight_kg": "25",
    "max_volume_cm3": 60000,
    "first_rack_distance_m": "5",
    "distance_step_m": "2.5",
}


# ------------------------------------------------------------------ manual creation


def test_create_full_path_and_location_code(client: TestClient, manager: dict, zone: dict) -> None:
    rack = post(
        client,
        f"/zones/{zone['id']}/racks",
        {"code": "r05", "distance_to_packing_m": 12.5},
        manager,
    )
    shelf = post(client, f"/racks/{rack['id']}/shelves", {"code": "s03", "level": 3}, manager)
    bin_ = post(
        client,
        f"/shelves/{shelf['id']}/bins",
        {"code": "b08", "max_weight_kg": 25, "max_volume_cm3": 60000},
        manager,
    )

    assert zone["code"] == "ZA"
    assert rack["distance_to_packing_m"] == "12.5"
    assert bin_["location_code"] == "WH01-ZA-R05-S03-B08"
    assert bin_["max_weight_kg"] == "25.000"


@pytest.mark.parametrize(
    ("url_part", "body"),
    [
        ("warehouses", {"code": "W1", "name": "x"}),
        ("warehouses", {"code": "WH1", "name": "x"}),
        ("zones", {"code": "Z1", "name": "x", "zone_type": "picking"}),
        ("zones", {"code": "ZA", "name": "x", "zone_type": "garage"}),
    ],
)
def test_invalid_codes_and_types_are_422(
    client: TestClient, manager: dict, zone: dict, url_part: str, body: dict
) -> None:
    url = "/warehouses" if url_part == "warehouses" else f"/warehouses/{zone['warehouse_id']}/zones"

    assert client.post(f"{API}{url}", json=body, headers=manager).status_code == 422


def test_duplicates_are_409(client: TestClient, manager: dict, zone: dict) -> None:
    duplicate_warehouse = client.post(
        f"{API}/warehouses", json={"code": "WH01", "name": "Again"}, headers=manager
    )
    duplicate_zone = client.post(
        f"{API}/warehouses/{zone['warehouse_id']}/zones",
        json={"code": "ZA", "name": "Again", "zone_type": "bulk"},
        headers=manager,
    )
    rack = post(client, f"/zones/{zone['id']}/racks", {"code": "R01"}, manager)
    post(client, f"/racks/{rack['id']}/shelves", {"code": "S01", "level": 1}, manager)
    duplicate_level = client.post(
        f"{API}/racks/{rack['id']}/shelves", json={"code": "S02", "level": 1}, headers=manager
    )

    assert duplicate_warehouse.status_code == 409
    assert duplicate_zone.status_code == 409
    assert duplicate_level.status_code == 409


def test_codes_cannot_be_changed(client: TestClient, manager: dict, zone: dict) -> None:
    response = client.patch(
        f"{API}/zones/{zone['id']}", json={"code": "ZB", "name": "Renamed"}, headers=manager
    )

    assert response.status_code == 200
    assert response.json()["code"] == "ZA"  # unknown field ignored, code unchanged
    assert response.json()["name"] == "Renamed"


# ---------------------------------------------------------------------- generation


def test_generate_creates_all_bins_with_codes_and_distances(
    client: TestClient, db_session: Session, manager: dict, zone: dict
) -> None:
    result = post(client, f"/zones/{zone['id']}/generate", GENERATE, manager)

    assert result == {
        "racks_created": 3,
        "shelves_created": 6,
        "bins_created": 24,
        "first_location_code": "WH01-ZA-R01-S01-B01",
        "last_location_code": "WH01-ZA-R03-S02-B04",
    }
    distances = db_session.scalars(
        select(Rack.distance_to_packing_m).where(Rack.zone_id == zone["id"]).order_by(Rack.code)
    ).all()
    assert distances == [Decimal("5.0"), Decimal("7.5"), Decimal("10.0")]
    levels = db_session.scalars(select(Shelf.level).order_by(Shelf.level).distinct()).all()
    assert levels == [1, 2]


def test_generate_again_continues_rack_numbering(
    client: TestClient, manager: dict, zone: dict
) -> None:
    post(client, f"/zones/{zone['id']}/generate", GENERATE, manager)

    second = post(client, f"/zones/{zone['id']}/generate", {**GENERATE, "racks": 1}, manager)

    assert second["first_location_code"] == "WH01-ZA-R04-S01-B01"


def test_generate_is_all_or_nothing(
    client: TestClient, db_session: Session, manager: dict, zone: dict
) -> None:
    # Plant a bin whose location code generation will only reach in its SECOND rack
    # (WH01-ZA-R09-S01-B01). If generation saved rack by rack, the 8 bins of R08 would
    # stay behind; all-or-nothing means nothing at all may be left.
    rack = post(client, f"/zones/{zone['id']}/racks", {"code": "R07"}, manager)
    shelf = post(client, f"/racks/{rack['id']}/shelves", {"code": "S01", "level": 1}, manager)
    post(
        client,
        f"/shelves/{shelf['id']}/bins",
        {"code": "B01", "max_weight_kg": 1, "max_volume_cm3": 1},
        manager,
    )
    db_session.execute(
        Bin.__table__.update()
        .where(Bin.location_code == "WH01-ZA-R07-S01-B01")
        .values(location_code="WH01-ZA-R09-S01-B01")  # first bin of the 2nd new rack
    )
    db_session.commit()
    bins_before = db_session.scalar(select(func.count(Bin.id)))
    racks_before = db_session.scalar(select(func.count(Rack.id)))

    response = client.post(f"{API}/zones/{zone['id']}/generate", json=GENERATE, headers=manager)

    assert response.status_code == 409
    assert "nothing was created" in response.json()["detail"]
    assert db_session.scalar(select(func.count(Bin.id))) == bins_before
    assert db_session.scalar(select(func.count(Rack.id))) == racks_before


def test_generate_limits(client: TestClient, manager: dict, zone: dict) -> None:
    too_many = {**GENERATE, "racks": 99, "shelves_per_rack": 20, "bins_per_shelf": 10}

    response = client.post(f"{API}/zones/{zone['id']}/generate", json=too_many, headers=manager)

    assert response.status_code == 422
    assert "At most 5000 bins" in response.text


# -------------------------------------------------------------------------- layout


def test_layout_tree_and_totals(client: TestClient, manager: dict, zone: dict) -> None:
    post(client, f"/zones/{zone['id']}/generate", {**GENERATE, "racks": 2}, manager)

    layout = client.get(f"{API}/warehouses/{zone['warehouse_id']}/layout", headers=manager).json()

    assert layout["code"] == "WH01"
    assert layout["totals"] == {
        "bins": 16,
        "active_bins": 16,
        "max_weight_kg": "400.000",
        "max_volume_cm3": 960000,
    }
    [zone_node] = layout["zones"]
    assert [r["code"] for r in zone_node["racks"]] == ["R01", "R02"]
    assert [s["level"] for s in zone_node["racks"][0]["shelves"]] == [1, 2]
    assert len(zone_node["racks"][0]["shelves"][0]["bins"]) == 4


def test_layout_orders_racks_by_distance_to_packing(
    client: TestClient, manager: dict, zone: dict
) -> None:
    post(
        client, f"/zones/{zone['id']}/racks", {"code": "R01", "distance_to_packing_m": 30}, manager
    )
    post(client, f"/zones/{zone['id']}/racks", {"code": "R02", "distance_to_packing_m": 4}, manager)

    layout = client.get(f"{API}/warehouses/{zone['warehouse_id']}/layout", headers=manager).json()

    assert [r["code"] for r in layout["zones"][0]["racks"]] == ["R02", "R01"]


# ------------------------------------------------------------------- archive/restore


def test_archiving_a_zone_archives_everything_below(
    client: TestClient, db_session: Session, manager: dict, zone: dict
) -> None:
    post(client, f"/zones/{zone['id']}/generate", {**GENERATE, "racks": 2}, manager)

    archived = client.patch(f"{API}/zones/{zone['id']}", json={"is_active": False}, headers=manager)
    layout = client.get(f"{API}/warehouses/{zone['warehouse_id']}/layout", headers=manager).json()
    full = client.get(
        f"{API}/warehouses/{zone['warehouse_id']}/layout?include_inactive=true", headers=manager
    ).json()

    assert archived.json()["is_active"] is False
    assert db_session.scalar(select(func.count(Bin.id)).where(Bin.is_active.is_(True))) == 0
    assert layout["zones"] == []  # archived records hidden by default
    assert full["totals"]["bins"] == 16 and full["totals"]["active_bins"] == 0


def test_restore_needs_active_parent(client: TestClient, manager: dict, zone: dict) -> None:
    post(client, f"/zones/{zone['id']}/generate", {**GENERATE, "racks": 1}, manager)
    rack_id = client.get(f"{API}/warehouses/{zone['warehouse_id']}/layout", headers=manager).json()[
        "zones"
    ][0]["racks"][0]["id"]
    client.patch(f"{API}/zones/{zone['id']}", json={"is_active": False}, headers=manager)

    blocked = client.patch(f"{API}/racks/{rack_id}", json={"is_active": True}, headers=manager)
    client.patch(f"{API}/zones/{zone['id']}", json={"is_active": True}, headers=manager)
    allowed = client.patch(f"{API}/racks/{rack_id}", json={"is_active": True}, headers=manager)

    assert blocked.status_code == 422
    assert allowed.json()["is_active"] is True


def test_cannot_add_children_to_archived_parent(
    client: TestClient, manager: dict, zone: dict
) -> None:
    client.patch(f"{API}/zones/{zone['id']}", json={"is_active": False}, headers=manager)

    response = client.post(f"{API}/zones/{zone['id']}/racks", json={"code": "R01"}, headers=manager)

    assert (response.status_code, response.json()["detail"]) == (422, "Zone is archived")


# -------------------------------------------------------------------- bins + scan


def test_bin_search_and_scan_by_code(
    client: TestClient, manager: dict, staff: dict, zone: dict
) -> None:
    post(client, f"/zones/{zone['id']}/generate", GENERATE, manager)

    page = client.get(f"{API}/bins?q=r02-s01&limit=2", headers=staff).json()
    scan = client.get(f"{API}/bins/by-code/wh01-za-r02-s01-b03", headers=staff)
    unknown = client.get(f"{API}/bins/by-code/WH99-ZZ-R01-S01-B01", headers=staff)

    assert page["total"] == 4
    assert [b["location_code"] for b in page["items"]] == [
        "WH01-ZA-R02-S01-B01",
        "WH01-ZA-R02-S01-B02",
    ]
    body = scan.json()
    assert body["location_code"] == "WH01-ZA-R02-S01-B03"
    assert (body["warehouse"]["code"], body["zone"]["code"], body["rack"]["code"]) == (
        "WH01",
        "ZA",
        "R02",
    )
    assert body["shelf"]["level"] == 1
    assert unknown.status_code == 404


def test_bin_capacity_update_and_fit_check(
    client: TestClient, db_session: Session, manager: dict, zone: dict
) -> None:
    post(client, f"/zones/{zone['id']}/generate", {**GENERATE, "racks": 1}, manager)
    bin_id = client.get(f"{API}/bins?limit=1", headers=manager).json()["items"][0]["id"]
    product = create_product(
        db_session, create_category(db_session), "BOX-1", weight_kg=Decimal("2.000")
    )  # 10 x 10 x 10 cm = 1 000 cm³

    client.patch(f"{API}/bins/{bin_id}", json={"max_weight_kg": "10"}, headers=manager)
    fits = client.get(
        f"{API}/bins/{bin_id}/fit?product_id={product.id}&quantity=5", headers=manager
    )
    too_heavy = client.get(
        f"{API}/bins/{bin_id}/fit?product_id={product.id}&quantity=6", headers=manager
    )

    assert fits.json()["fits"] is True
    assert fits.json()["max_weight_kg"] == "10.000"
    assert too_heavy.json()["fits"] is False
    assert too_heavy.json()["reasons"][0].startswith("Too heavy")

    # What is already in the bin counts: after receiving 3 units only 2 more fit.
    client.post(
        f"{API}/inventory/receive",
        json={"product_id": product.id, "bin_id": bin_id, "quantity": 3},
        headers=manager,
    )
    now = client.get(f"{API}/bins/{bin_id}/fit?product_id={product.id}&quantity=3", headers=manager)
    assert now.json()["fits"] is False
    assert now.json()["used_weight_kg"] == "6.000"
    assert (
        client.get(
            f"{API}/bins/{bin_id}/fit?product_id={product.id}&quantity=2", headers=manager
        ).json()["fits"]
        is True
    )


# --------------------------------------------------------------------- permissions


def test_staff_reads_but_cannot_change(client: TestClient, staff: dict, zone: dict) -> None:
    warehouse_id = zone["warehouse_id"]

    assert client.get(f"{API}/warehouses", headers=staff).status_code == 200
    assert client.get(f"{API}/warehouses/{warehouse_id}/layout", headers=staff).status_code == 200
    assert (
        client.post(
            f"{API}/warehouses", json={"code": "WH02", "name": "x"}, headers=staff
        ).status_code
        == 403
    )
    assert (
        client.patch(f"{API}/zones/{zone['id']}", json={"name": "x"}, headers=staff).status_code
        == 403
    )
    assert (
        client.post(f"{API}/zones/{zone['id']}/generate", json=GENERATE, headers=staff).status_code
        == 403
    )


def test_customers_cannot_see_the_layout(
    client: TestClient, db_session: Session, zone: dict
) -> None:
    customer = auth_headers(user_with_role(db_session, RoleName.CUSTOMER))

    assert client.get(f"{API}/warehouses", headers=customer).status_code == 403
    assert client.get(f"{API}/bins", headers=customer).status_code == 403
    assert (
        client.get(f"{API}/warehouses/{zone['warehouse_id']}/layout", headers=customer).status_code
        == 403
    )


def test_not_found_paths(client: TestClient, manager: dict) -> None:
    assert client.get(f"{API}/warehouses/999999/layout", headers=manager).status_code == 404
    assert client.patch(f"{API}/racks/999999", json={}, headers=manager).status_code == 404
    assert (
        client.post(f"{API}/zones/999999/generate", json=GENERATE, headers=manager).status_code
        == 404
    )
