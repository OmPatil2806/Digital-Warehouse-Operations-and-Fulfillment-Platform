"""Master data and warehouse layout of the small dataset (and a full-size layout)."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.dashboard_service import DashboardService, DateRange
from data_generation import catalog_data
from data_generation.config import get_config
from data_generation.context import GenerationContext
from data_generation.database import GenerationError, prepare_database
from data_generation.generate_master_data import category_plan, ean13
from data_generation.generate_warehouse_layout import BIN_CAPACITY, max_weight, zone_specs
from data_generation.patterns import CATEGORIES, UNITS_PER_ORDER, expected_daily_units

Small = tuple[GenerationContext, Engine]
Builder = Callable[..., Small]


def rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql))]


def scalar(engine: Engine, sql: str) -> object:
    return rows(engine, sql)[0][0]


def test_row_counts_match_the_configuration(small: Small) -> None:
    ctx, engine = small
    counts = {
        table: scalar(engine, f"SELECT COUNT(*) FROM {table}")
        for table in (
            "categories",
            "products",
            "suppliers",
            "customers",
            "carriers",
            "warehouses",
            "zones",
            "racks",
            "shelves",
            "bins",
        )
    }
    assert counts == {
        "categories": 8,
        "products": 50,
        "suppliers": 10,
        "customers": 200,
        "carriers": 4,
        "warehouses": 1,
        "zones": 4,
        "racks": 20,
        "shelves": 60,
        "bins": 300,
    }
    offers = scalar(engine, "SELECT COUNT(*) FROM supplier_products")
    assert 50 < offers <= 100  # every product, some with a second source
    assert ctx.writer.counts["bins"] == 300


def test_categories_form_a_small_tree(small: Small) -> None:
    _, engine = small
    tree = dict(
        rows(
            engine,
            "SELECT c.name, p.name FROM categories c LEFT JOIN categories p ON c.parent_id = p.id",
        )
    )
    assert tree["Laptops"] == "Electronics"
    assert tree["Accessories"] == "Electronics"
    assert tree["Food & Beverages"] is None
    assert set(tree) == set(CATEGORIES)


def test_products_are_realistic_and_unique(small: Small) -> None:
    ctx, engine = small
    products = rows(
        engine,
        "SELECT sku, barcode, unit_price, unit_cost, min_stock, max_stock, name FROM products",
    )
    assert len({p[0] for p in products}) == 50
    assert len({p[1] for p in products}) == 50
    for sku, barcode, price, cost, min_stock, max_stock, name in products:
        assert re.fullmatch(r"(LAP|ELE|ACC|OFF|AUT|TOO|HOM|FOO)-\d{5}", sku)
        digits = [int(d) for d in barcode]
        assert sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits)) % 10 == 0
        # Money is stored in cents
        assert 0 < cost < price
        assert price % 100 in (90, 99)
        assert 1 <= min_stock < max_stock
        assert len(name.split()) >= 3
    assert {p.category for p in ctx.products} == set(CATEGORIES)


def test_category_plan_follows_the_shares() -> None:
    plan = category_plan(2_000)
    assert len(plan) == 2_000
    assert plan.count("Accessories") == 320  # 16 %
    assert plan.count("Laptops") == 160  # 8 %
    small = category_plan(8)
    assert sorted(small) == sorted(CATEGORIES)  # at least one of each


def test_ean13() -> None:
    assert ean13(1) == "4000000000013"
    assert len({ean13(i) for i in range(1, 5_000)}) == 4_999


def test_demand_is_scaled_to_the_order_volume(small: Small) -> None:
    ctx, _ = small
    config = ctx.config
    total = sum(
        expected_daily_units(p.profile, config.start_date, config.days) for p in ctx.products
    )
    assert total == pytest.approx(config.orders_per_day * UNITS_PER_ORDER, rel=0.01)


def test_every_product_has_one_preferred_supplier_of_its_category(small: Small) -> None:
    ctx, engine = small
    preferred = dict(
        rows(engine, "SELECT product_id, supplier_id FROM supplier_products WHERE is_preferred")
    )
    defaults = dict(rows(engine, "SELECT id, default_supplier_id FROM products"))
    assert preferred == defaults
    suppliers = {s.id: s for s in ctx.suppliers}
    for product in ctx.products:
        assert product.category in suppliers[product.supplier_ids[0]].categories
    second = rows(
        engine,
        "SELECT o.unit_cost, p.unit_cost FROM supplier_products o "
        "JOIN products p ON p.id = o.product_id WHERE NOT o.is_preferred",
    )
    assert all(offer > own for offer, own in second)


def test_supplier_ratings_estimate_their_true_reliability(small: Small) -> None:
    ctx, engine = small
    stored = dict(rows(engine, "SELECT id, reliability_score FROM suppliers"))
    for supplier in ctx.suppliers:
        assert abs(stored[supplier.id] / 100 - supplier.profile.reliability) < 0.15
    countries = dict(rows(engine, "SELECT id, country FROM suppliers"))
    for supplier in ctx.suppliers:
        if countries[supplier.id] in ("Taiwan", "China"):
            assert supplier.profile.promised_lead_days >= 18


def test_customers(small: Small) -> None:
    ctx, engine = small
    types = rows(engine, "SELECT customer_type, COUNT(*) FROM customers GROUP BY customer_type")
    business = dict(types)["business"] / 200
    assert business == pytest.approx(0.6, abs=0.1)
    assert scalar(engine, "SELECT COUNT(DISTINCT code) FROM customers") == 200
    assert max(c.activity for c in ctx.customers) > 3  # a few very active accounts


def test_layout_codes_and_capacities(small: Small) -> None:
    ctx, engine = small
    codes = [r[0] for r in rows(engine, "SELECT location_code FROM bins")]
    assert all(re.fullmatch(r"WH01-Z[A-Z]-R\d{2}-S\d{2}-B\d{2}", c) for c in codes)
    zones = rows(engine, "SELECT code, zone_type FROM zones ORDER BY id")
    assert zones == [("ZA", "picking"), ("ZB", "bulk"), ("ZC", "cold"), ("ZR", "returns")]
    by_level = {b.level: b.max_weight_kg for b in ctx.bins if b.zone_type == "picking"}
    assert by_level[1] == 2 * by_level[2] > by_level[3]  # heavy goods low


def test_racks_lie_further_away_the_higher_their_number(small: Small) -> None:
    _, engine = small
    distances = rows(
        engine,
        "SELECT r.zone_id, r.code, r.distance_to_packing_m FROM racks r ORDER BY r.zone_id, r.code",
    )
    for (zone_a, _, dist_a), (zone_b, _, dist_b) in zip(distances, distances[1:], strict=False):
        if zone_a == zone_b:
            assert dist_b > dist_a


def test_every_product_fits_somewhere(small: Small) -> None:
    ctx, _ = small
    for product in ctx.products:
        assert any(
            b.max_weight_kg >= product.weight_kg and b.max_volume_cm3 >= product.volume_cm3
            for b in ctx.bins
            if b.zone_type != "returns"
        ), product.sku


def test_full_size_layout(tmp_path: Path, builder: Builder) -> None:
    ctx, engine = builder(tmp_path / "full.db", "full", products=8, customers=1, orders=10)
    assert scalar(engine, "SELECT COUNT(*) FROM bins") == 4_320
    assert scalar(engine, "SELECT COUNT(*) FROM zones") == 18
    assert scalar(engine, "SELECT COUNT(*) FROM racks") == 180
    per_warehouse = rows(
        engine,
        "SELECT w.code, COUNT(*) FROM zones z JOIN warehouses w ON w.id = z.warehouse_id "
        "GROUP BY w.code",
    )
    assert per_warehouse == [("WH01", 6), ("WH02", 6), ("WH03", 6)]
    types = {b.zone_type for b in ctx.bins}
    assert types == {"picking", "bulk", "cold", "hazardous", "returns"}


def test_zone_specs_always_include_returns() -> None:
    assert [z[2] for z in zone_specs(2)] == ["picking", "returns"]
    with pytest.raises(ValueError):
        zone_specs(1)
    with pytest.raises(ValueError):
        zone_specs(7)


def test_generation_is_reproducible(tmp_path: Path, small: Small, builder: Builder) -> None:
    _, first = small
    _, again = builder(tmp_path / "again.db")
    query = "SELECT * FROM products ORDER BY id"
    assert rows(again, query) == rows(first, query)
    query = "SELECT * FROM bins ORDER BY id"
    assert rows(again, query) == rows(first, query)

    _, other = builder(tmp_path / "other.db", seed=1)
    assert get_config("small", seed=1).seed == 1
    assert rows(other, "SELECT name FROM products") != rows(first, "SELECT name FROM products")


def test_refuses_to_overwrite_an_existing_database(tmp_path: Path) -> None:
    path = tmp_path / "exists.db"
    path.write_bytes(b"")
    with pytest.raises(GenerationError, match="--replace"):
        prepare_database(path)
    engine = prepare_database(path, replace=True)
    assert scalar(engine, "SELECT COUNT(*) FROM roles") == 4  # migrated


def test_the_application_reads_the_generated_data(small: Small) -> None:
    ctx, engine = small
    with Session(engine) as session:
        dashboard = DashboardService(session).warehouse(
            DateRange(date(2026, 11, 1), date(2026, 11, 7))
        )
    assert dashboard.total.bins == 300
    assert [z.code for z in dashboard.zones] == ["ZA", "ZB", "ZC", "ZR"]
    assert Decimal(dashboard.total.max_weight_kg) > 0


def test_every_product_template_fits_a_bin_of_its_storage_zone() -> None:
    """Largest possible variant of every template (size +8 %, heaviest weight)."""
    for category, templates in catalog_data.PRODUCT_TEMPLATES.items():
        for name, (_low, heaviest), size, _price, storage in templates:
            volume = size[0] * size[1] * size[2] * 1.08**3
            weight_limit = float(max_weight(storage, 1))
            volume_limit = BIN_CAPACITY[storage][1]
            assert heaviest <= weight_limit, f"{category}: {name} too heavy for {storage}"
            assert volume <= volume_limit, f"{category}: {name} too big for {storage}"
