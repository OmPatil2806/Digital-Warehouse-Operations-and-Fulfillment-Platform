"""Tests for the catalog models and the exact-decimal column type."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.models.catalog import Category, Product, Supplier, SupplierProduct


def make_category(db: Session, name: str = "Electronics", **extra: object) -> Category:
    category = Category(name=name, **extra)
    db.add(category)
    db.commit()
    return category


def make_supplier(db: Session, code: str = "SUP-001", **extra: object) -> Supplier:
    supplier = Supplier(code=code, name=extra.pop("name", f"Supplier {code}"), **extra)
    db.add(supplier)
    db.commit()
    return supplier


def product_values(category: Category, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "sku": "LAP-001",
        "name": "Laptop 14 inch",
        "category_id": category.id,
        "unit_price": Decimal("899.99"),
        "unit_cost": Decimal("650.00"),
        "weight_kg": Decimal("1.450"),
        "length_cm": Decimal("33.0"),
        "width_cm": Decimal("23.5"),
        "height_cm": Decimal("2.0"),
    }
    values.update(overrides)
    return values


def make_product(db: Session, category: Category, **overrides: object) -> Product:
    product = Product(**product_values(category, **overrides))
    db.add(product)
    db.commit()
    return product


def expect_integrity_error(db: Session, obj: object) -> None:
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ------------------------------------------------------------------------ products


def test_product_round_trip_keeps_exact_decimals(db_session: Session) -> None:
    product = make_product(db_session, make_category(db_session))
    db_session.expire_all()  # force a fresh read from the database

    loaded = db_session.get(Product, product.id)
    assert loaded is not None
    assert loaded.unit_price == Decimal("899.99")
    assert loaded.weight_kg == Decimal("1.450")
    assert loaded.length_cm == Decimal("33.0")
    assert loaded.margin == Decimal("249.99")
    assert loaded.volume_cm3 == Decimal("1551.000")
    assert loaded.is_active is True
    assert loaded.min_stock == 0
    assert loaded.max_stock is None


def test_decimals_are_stored_as_integers_in_the_smallest_unit(db_session: Session) -> None:
    product = make_product(db_session, make_category(db_session))

    row = db_session.execute(
        text("SELECT unit_price, weight_kg, length_cm FROM products WHERE id = :id"),
        {"id": product.id},
    ).one()

    assert tuple(row) == (89999, 1450, 330)  # cents, grams, millimetres


def test_sql_comparisons_and_sorting_use_real_values(db_session: Session) -> None:
    category = make_category(db_session)
    make_product(db_session, category, sku="A", unit_price=Decimal("9.99"))
    make_product(db_session, category, sku="B", unit_price=Decimal("100.00"))
    make_product(db_session, category, sku="C", unit_price=Decimal("19.50"))

    expensive = db_session.scalars(
        select(Product.sku).where(Product.unit_price > Decimal("10")).order_by(Product.unit_price)
    ).all()

    assert expensive == ["C", "B"]


def test_too_many_decimal_places_are_rejected_not_rounded(db_session: Session) -> None:
    category = make_category(db_session)
    db_session.add(Product(**product_values(category, unit_price=Decimal("1.005"))))

    with pytest.raises(StatementError, match="more than 2 decimal places"):
        db_session.commit()
    db_session.rollback()


def test_floats_are_rejected_for_money(db_session: Session) -> None:
    category = make_category(db_session)
    db_session.add(Product(**product_values(category, unit_price=19.99)))

    with pytest.raises(StatementError, match="does not accept float"):
        db_session.commit()
    db_session.rollback()


def test_sku_must_be_unique(db_session: Session) -> None:
    category = make_category(db_session)
    make_product(db_session, category, sku="DUP-1")

    expect_integrity_error(db_session, Product(**product_values(category, sku="DUP-1")))


def test_barcode_is_optional_but_unique(db_session: Session) -> None:
    category = make_category(db_session)
    make_product(db_session, category, sku="NO-BARCODE-1")
    make_product(db_session, category, sku="NO-BARCODE-2")  # several NULL barcodes are fine
    make_product(db_session, category, sku="BC-1", barcode="4006381333931")

    expect_integrity_error(
        db_session, Product(**product_values(category, sku="BC-2", barcode="4006381333931"))
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"unit_price": Decimal("-1.00")},
        {"unit_cost": Decimal("-0.01")},
        {"weight_kg": Decimal("0")},
        {"length_cm": Decimal("0")},
        {"height_cm": Decimal("-2.0")},
        {"min_stock": -1},
        {"min_stock": 10, "max_stock": 5},
    ],
)
def test_product_check_constraints(db_session: Session, overrides: dict[str, object]) -> None:
    category = make_category(db_session)

    expect_integrity_error(db_session, Product(**product_values(category, **overrides)))


def test_max_stock_equal_to_min_stock_is_allowed(db_session: Session) -> None:
    product = make_product(db_session, make_category(db_session), min_stock=5, max_stock=5)

    assert product.max_stock == 5


def test_product_requires_an_existing_category(db_session: Session) -> None:
    category = make_category(db_session)

    expect_integrity_error(db_session, Product(**product_values(category, category_id=999_999)))


def test_category_in_use_cannot_be_deleted(db_session: Session) -> None:
    category = make_category(db_session)
    make_product(db_session, category)

    # RESTRICT is enforced immediately, when the DELETE runs.
    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM categories WHERE id = :id"), {"id": category.id})
    db_session.rollback()


def test_deleting_default_supplier_clears_it_on_the_product(db_session: Session) -> None:
    supplier = make_supplier(db_session)
    product = make_product(db_session, make_category(db_session), default_supplier_id=supplier.id)

    db_session.execute(text("DELETE FROM suppliers WHERE id = :id"), {"id": supplier.id})
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(Product, product.id).default_supplier_id is None


# ---------------------------------------------------------------------- categories


def test_categories_can_be_nested(db_session: Session) -> None:
    electronics = make_category(db_session, "Electronics")
    laptops = make_category(db_session, "Laptops", parent_id=electronics.id)
    db_session.expire_all()

    assert db_session.get(Category, laptops.id).parent.name == "Electronics"
    assert [child.name for child in db_session.get(Category, electronics.id).children] == [
        "Laptops"
    ]


def test_category_name_must_be_unique(db_session: Session) -> None:
    make_category(db_session, "Tools")

    expect_integrity_error(db_session, Category(name="Tools"))


def test_category_cannot_be_its_own_parent(db_session: Session) -> None:
    category = make_category(db_session, "Loop")
    category.parent_id = category.id

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ----------------------------------------------------------------------- suppliers


def test_supplier_defaults(db_session: Session) -> None:
    supplier = make_supplier(db_session)
    db_session.expire_all()

    loaded = db_session.get(Supplier, supplier.id)
    assert loaded.lead_time_days == 7
    assert loaded.reliability_score == Decimal("0.95")
    assert loaded.is_active is True


def test_supplier_code_must_be_unique(db_session: Session) -> None:
    make_supplier(db_session, "SUP-777")

    expect_integrity_error(db_session, Supplier(code="SUP-777", name="Copy"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"lead_time_days": -1},
        {"reliability_score": Decimal("1.01")},
        {"reliability_score": Decimal("-0.01")},
    ],
)
def test_supplier_check_constraints(db_session: Session, overrides: dict[str, object]) -> None:
    expect_integrity_error(db_session, Supplier(code="SUP-X", name="X", **overrides))


# --------------------------------------------------------------- supplier products


def test_supplier_product_link_and_effective_lead_time(db_session: Session) -> None:
    supplier = make_supplier(db_session, lead_time_days=10)
    product = make_product(db_session, make_category(db_session))
    link = SupplierProduct(
        supplier_id=supplier.id, product_id=product.id, unit_cost=Decimal("640.00")
    )
    db_session.add(link)
    db_session.commit()

    assert link.min_order_qty == 1
    assert link.is_preferred is False
    assert link.effective_lead_time_days == 10  # falls back to the supplier's lead time
    link.lead_time_days = 3
    assert link.effective_lead_time_days == 3
    assert [p.product.sku for p in supplier.supplied_products] == ["LAP-001"]


def test_same_supplier_cannot_list_a_product_twice(db_session: Session) -> None:
    supplier = make_supplier(db_session)
    product = make_product(db_session, make_category(db_session))
    db_session.add(
        SupplierProduct(supplier_id=supplier.id, product_id=product.id, unit_cost=Decimal("1"))
    )
    db_session.commit()

    expect_integrity_error(
        db_session,
        SupplierProduct(supplier_id=supplier.id, product_id=product.id, unit_cost=Decimal("2")),
    )


def test_supplier_product_min_order_qty_must_be_positive(db_session: Session) -> None:
    supplier = make_supplier(db_session)
    product = make_product(db_session, make_category(db_session))

    expect_integrity_error(
        db_session,
        SupplierProduct(
            supplier_id=supplier.id, product_id=product.id, unit_cost=Decimal("1"), min_order_qty=0
        ),
    )


def test_deleting_a_supplier_removes_its_product_links(db_session: Session) -> None:
    supplier = make_supplier(db_session)
    product = make_product(db_session, make_category(db_session))
    db_session.add(
        SupplierProduct(supplier_id=supplier.id, product_id=product.id, unit_cost=Decimal("1"))
    )
    db_session.commit()

    db_session.execute(text("DELETE FROM suppliers WHERE id = :id"), {"id": supplier.id})
    db_session.commit()

    assert db_session.scalars(select(SupplierProduct)).all() == []
    assert db_session.get(Product, product.id) is not None  # the product itself stays
