"""Tests for the warehouse hierarchy models: Warehouse > Zone > Rack > Shelf > Bin."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.warehouse import (
    Bin,
    Rack,
    Shelf,
    Warehouse,
    Zone,
    ZoneType,
    build_location_code,
)


def add(db: Session, obj: object) -> object:
    db.add(obj)
    db.commit()
    return obj


def make_tree(db: Session) -> dict[str, object]:
    """WH01 > ZA (picking) > R05 > S03 (level 3) > B08."""
    warehouse = add(db, Warehouse(code="WH01", name="Main warehouse"))
    zone = add(db, Zone(warehouse_id=warehouse.id, code="ZA", name="Zone A", zone_type="picking"))
    rack = add(db, Rack(zone_id=zone.id, code="R05", distance_to_packing_m=Decimal("12.5")))
    shelf = add(db, Shelf(rack_id=rack.id, code="S03", level=3))
    bin_ = add(
        db,
        Bin(
            shelf_id=shelf.id,
            code="B08",
            location_code=build_location_code("WH01", "ZA", "R05", "S03", "B08"),
            max_weight_kg=Decimal("25.000"),
            max_volume_cm3=60_000,
        ),
    )
    return {"warehouse": warehouse, "zone": zone, "rack": rack, "shelf": shelf, "bin": bin_}


def expect_integrity_error(db: Session, obj: object) -> None:
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_build_location_code() -> None:
    assert build_location_code("WH01", "ZA", "R05", "S03", "B08") == "WH01-ZA-R05-S03-B08"


def test_full_hierarchy_round_trip(db_session: Session) -> None:
    tree = make_tree(db_session)
    db_session.expire_all()

    bin_ = db_session.get(Bin, tree["bin"].id)
    assert bin_.location_code == "WH01-ZA-R05-S03-B08"
    assert bin_.max_weight_kg == Decimal("25.000")
    assert bin_.max_volume_cm3 == 60_000
    assert bin_.is_active is True
    # Walk up the tree through the relationships
    assert bin_.shelf.level == 3
    assert bin_.shelf.rack.distance_to_packing_m == Decimal("12.5")
    assert bin_.shelf.rack.zone.zone_type == ZoneType.PICKING
    assert bin_.shelf.rack.zone.warehouse.code == "WH01"


def test_children_are_ordered(db_session: Session) -> None:
    tree = make_tree(db_session)
    rack = tree["rack"]
    add(db_session, Shelf(rack_id=rack.id, code="S01", level=1))
    add(db_session, Shelf(rack_id=rack.id, code="S02", level=2))
    db_session.expire_all()

    assert [s.level for s in db_session.get(Rack, rack.id).shelves] == [1, 2, 3]


def test_rack_distance_defaults_to_zero(db_session: Session) -> None:
    zone = make_tree(db_session)["zone"]

    rack = add(db_session, Rack(zone_id=zone.id, code="R01"))
    db_session.expire_all()

    assert db_session.get(Rack, rack.id).distance_to_packing_m == Decimal("0.0")


# ------------------------------------------------------------------- uniqueness rules


def test_warehouse_code_is_unique(db_session: Session) -> None:
    make_tree(db_session)

    expect_integrity_error(db_session, Warehouse(code="WH01", name="Copy"))


def test_zone_code_is_unique_within_warehouse_only(db_session: Session) -> None:
    tree = make_tree(db_session)
    other = add(db_session, Warehouse(code="WH02", name="Second"))

    # Same zone code in another warehouse is fine
    add(db_session, Zone(warehouse_id=other.id, code="ZA", name="A", zone_type="bulk"))
    expect_integrity_error(
        db_session,
        Zone(warehouse_id=tree["warehouse"].id, code="ZA", name="Dup", zone_type="bulk"),
    )


def test_rack_code_is_unique_within_zone(db_session: Session) -> None:
    tree = make_tree(db_session)

    expect_integrity_error(db_session, Rack(zone_id=tree["zone"].id, code="R05"))


def test_shelf_code_and_level_are_unique_within_rack(db_session: Session) -> None:
    rack = make_tree(db_session)["rack"]

    expect_integrity_error(db_session, Shelf(rack_id=rack.id, code="S03", level=9))
    expect_integrity_error(db_session, Shelf(rack_id=rack.id, code="S09", level=3))


def test_bin_code_is_unique_within_shelf(db_session: Session) -> None:
    tree = make_tree(db_session)

    expect_integrity_error(
        db_session,
        Bin(
            shelf_id=tree["shelf"].id,
            code="B08",
            location_code="something-else",
            max_weight_kg=Decimal("1"),
            max_volume_cm3=1,
        ),
    )


def test_location_code_is_unique_across_the_system(db_session: Session) -> None:
    tree = make_tree(db_session)
    other_shelf = add(db_session, Shelf(rack_id=tree["rack"].id, code="S04", level=4))

    expect_integrity_error(
        db_session,
        Bin(
            shelf_id=other_shelf.id,
            code="B01",
            location_code="WH01-ZA-R05-S03-B08",  # already used
            max_weight_kg=Decimal("1"),
            max_volume_cm3=1,
        ),
    )


# --------------------------------------------------------------------- check rules


def test_invalid_zone_type_is_rejected(db_session: Session) -> None:
    warehouse = add(db_session, Warehouse(code="WH09", name="W"))

    expect_integrity_error(
        db_session, Zone(warehouse_id=warehouse.id, code="ZX", name="X", zone_type="garage")
    )


@pytest.mark.parametrize("zone_type", list(ZoneType))
def test_all_zone_types_are_accepted(db_session: Session, zone_type: ZoneType) -> None:
    warehouse = add(db_session, Warehouse(code="WH09", name="W"))

    zone = add(
        db_session, Zone(warehouse_id=warehouse.id, code="ZT", name="T", zone_type=zone_type)
    )

    assert zone.id is not None


def test_negative_rack_distance_is_rejected(db_session: Session) -> None:
    zone = make_tree(db_session)["zone"]

    expect_integrity_error(
        db_session, Rack(zone_id=zone.id, code="R99", distance_to_packing_m=Decimal("-1"))
    )


def test_shelf_level_must_be_at_least_one(db_session: Session) -> None:
    rack = make_tree(db_session)["rack"]

    expect_integrity_error(db_session, Shelf(rack_id=rack.id, code="S00", level=0))


@pytest.mark.parametrize(
    ("weight", "volume"), [(Decimal("0"), 100), (Decimal("-1"), 100), (Decimal("5"), 0)]
)
def test_bin_capacity_must_be_positive(db_session: Session, weight: Decimal, volume: int) -> None:
    shelf = make_tree(db_session)["shelf"]

    expect_integrity_error(
        db_session,
        Bin(
            shelf_id=shelf.id,
            code="B99",
            location_code="WH01-ZA-R05-S03-B99",
            max_weight_kg=weight,
            max_volume_cm3=volume,
        ),
    )


# ------------------------------------------------------------------ delete protection


@pytest.mark.parametrize(
    ("table", "level"),
    [("warehouses", "warehouse"), ("zones", "zone"), ("racks", "rack"), ("shelves", "shelf")],
)
def test_records_with_children_cannot_be_deleted(
    db_session: Session, table: str, level: str
) -> None:
    tree = make_tree(db_session)

    with pytest.raises(IntegrityError):
        db_session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": tree[level].id})
    db_session.rollback()


def test_empty_records_can_be_deleted_bottom_up(db_session: Session) -> None:
    tree = make_tree(db_session)

    for table, level in [
        ("bins", "bin"),
        ("shelves", "shelf"),
        ("racks", "rack"),
        ("zones", "zone"),
        ("warehouses", "warehouse"),
    ]:
        db_session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": tree[level].id})
    db_session.commit()

    assert db_session.scalars(select(Warehouse)).all() == []


def _chain(db: Session, depth: int) -> list[object]:
    """Build only the first `depth` levels: [warehouse, zone, rack, shelf, bin][:depth]."""
    levels: list[object] = [add(db, Warehouse(code="WH05", name="Chain"))]
    if depth >= 2:
        levels.append(
            add(db, Zone(warehouse_id=levels[0].id, code="ZC", name="C", zone_type="bulk"))
        )
    if depth >= 3:
        levels.append(add(db, Rack(zone_id=levels[1].id, code="R01")))
    if depth >= 4:
        levels.append(add(db, Shelf(rack_id=levels[2].id, code="S01", level=1)))
    if depth >= 5:
        levels.append(
            add(
                db,
                Bin(
                    shelf_id=levels[3].id,
                    code="B01",
                    location_code="WH05-ZC-R01-S01-B01",
                    max_weight_kg=Decimal("1"),
                    max_volume_cm3=1,
                ),
            )
        )
    return levels


@pytest.mark.parametrize(
    ("parent_table", "depth"),
    [("warehouses", 2), ("zones", 3), ("racks", 4), ("shelves", 5)],
)
def test_each_level_protects_its_direct_child(
    db_session: Session, parent_table: str, depth: int
) -> None:
    """The parent has exactly one EMPTY child, so only this level's rule can block it."""
    chain = _chain(db_session, depth)
    parent = chain[depth - 2]

    with pytest.raises(IntegrityError):
        db_session.execute(text(f"DELETE FROM {parent_table} WHERE id = :id"), {"id": parent.id})
    db_session.rollback()
