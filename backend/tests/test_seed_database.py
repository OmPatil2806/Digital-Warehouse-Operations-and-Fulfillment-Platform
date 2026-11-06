"""Tests for scripts/seed_database.py (demo data)."""

import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.audit import Alert
from app.models.catalog import Category, Product, Supplier, SupplierProduct
from app.models.inventory import Inventory, InventoryMovement, StockAdjustment
from app.models.user import User
from app.models.warehouse import Bin, Warehouse, Zone
from app.services.capacity import product_fits_bin
from app.services.inventory_service import InventoryService
from tests.factories import create_user

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_database.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_database_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def count(db: Session, model: type) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def session_factory(db: Session):  # noqa: ANN201
    @contextmanager
    def _factory() -> Iterator[Session]:
        yield db

    return _factory


def test_seed_creates_the_demo_dataset(script: ModuleType, db_session: Session) -> None:
    report = script.seed(db_session)

    assert report.created == {
        "users": 4,
        "categories": 8,
        "suppliers": 10,
        "products": 50,
        "supplier offers": 60,
        "warehouses": 1,
        "zones": 4,
        "bins": 274,
        "stocked products": 49,  # one product is deliberately out of stock
        "pending requests": 1,
        "carriers": 4,
        "customers": 3,
        "orders": 7,
        "purchase orders": 3,
    }
    assert (count(db_session, Category), count(db_session, Product)) == (8, 50)
    assert count(db_session, Bin) == 274


def test_seed_is_idempotent(script: ModuleType, db_session: Session) -> None:
    script.seed(db_session)
    totals = [
        count(db_session, m) for m in (User, Category, Supplier, Product, SupplierProduct, Bin)
    ]

    second = script.seed(db_session)

    assert second.created == {}
    assert second.skipped["products"] == 50
    assert second.skipped["bins"] == 274
    assert [
        count(db_session, m) for m in (User, Category, Supplier, Product, SupplierProduct, Bin)
    ] == totals


def test_seeded_data_is_consistent(script: ModuleType, db_session: Session) -> None:
    script.seed(db_session)
    products = db_session.scalars(select(Product)).all()

    # Every product has a category, a default supplier and exactly one preferred offer
    for product in products:
        assert product.category.is_active
        assert product.default_supplier is not None
        offers = db_session.scalars(
            select(SupplierProduct).where(SupplierProduct.product_id == product.id)
        ).all()
        assert sum(o.is_preferred for o in offers) == 1
        preferred = next(o for o in offers if o.is_preferred)
        assert preferred.supplier_id == product.default_supplier_id
        assert product.margin > 0  # every demo product sells above cost

    # Barcodes are valid, unique EAN-13 codes
    barcodes = [p.barcode for p in products]
    assert len(set(barcodes)) == 50
    for code in barcodes:
        digits = [int(d) for d in code]
        assert len(digits) == 13
        assert sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits)) % 10 == 0

    # Sub-categories hang below Electronics
    laptops = db_session.scalars(select(Category).where(Category.name == "Laptops")).one()
    assert laptops.parent.name == "Electronics"


def test_seeded_layout_has_four_zone_types_and_valid_codes(
    script: ModuleType, db_session: Session
) -> None:
    script.seed(db_session)

    warehouse = db_session.scalars(select(Warehouse)).one()
    zones = {z.code: z.zone_type for z in db_session.scalars(select(Zone))}
    codes = db_session.scalars(select(Bin.location_code)).all()

    assert warehouse.code == "WH01"
    assert zones == {"ZA": "picking", "ZB": "bulk", "ZC": "cold", "ZR": "returns"}
    assert len(set(codes)) == 274
    assert all(code.startswith("WH01-Z") for code in codes)
    assert "WH01-ZA-R01-S01-B01" in codes


def test_every_product_fits_some_bin(script: ModuleType, db_session: Session) -> None:
    """The demo layout must be able to store at least one unit of every demo product."""
    script.seed(db_session)
    bins = db_session.scalars(select(Bin)).all()
    largest = {}
    for bin_ in bins:  # one representative bin per capacity profile
        largest.setdefault((bin_.max_weight_kg, bin_.max_volume_cm3), bin_)

    for product in db_session.scalars(select(Product)):
        assert any(product_fits_bin(product, b).fits for b in largest.values()), product.sku


def test_demo_users_can_log_in(script: ModuleType, db_session: Session, client: TestClient) -> None:
    script.seed(db_session)

    for email, _, role in script.DEMO_USERS:
        user = db_session.scalars(select(User).where(User.email == email)).one()
        assert user.role_names == {role.value}
        assert verify_password(script.DEMO_PASSWORD, user.hashed_password)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "manager@example.com", "password": script.DEMO_PASSWORD},
    )
    assert login.status_code == 200


def test_seed_does_not_touch_an_existing_user(script: ModuleType, db_session: Session) -> None:
    mine = create_user(db_session, "admin@example.com", password="My-own-pass-1")

    script.seed(db_session)

    db_session.refresh(mine)
    assert verify_password("My-own-pass-1", mine.hashed_password)  # password not replaced


def test_reset_removes_demo_data_but_keeps_other_users(
    script: ModuleType, db_session: Session
) -> None:
    create_user(db_session, "om@example.com")
    script.seed(db_session)

    script.reset(db_session)

    assert [count(db_session, m) for m in (Category, Supplier, Product, Bin, Warehouse)] == [0] * 5
    emails = set(db_session.scalars(select(User.email)))
    assert emails == {"om@example.com"}


def test_reset_is_refused_outside_development(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        script, "get_settings", lambda: Settings(app_env="production", secret_key="x" * 64)
    )

    with pytest.raises(script.SeedError, match="only allowed in development"):
        script.reset(db_session)
    assert script.main([], session_factory=session_factory(db_session)) == 1


def test_main_reset_asks_for_confirmation(
    script: ModuleType, db_session: Session, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    script.seed(db_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    code = script.main(["--reset"], session_factory=session_factory(db_session))

    assert code == 1
    assert "Cancelled" in capsys.readouterr().out
    assert count(db_session, Product) == 50  # nothing deleted


def test_main_prints_a_summary(script: ModuleType, db_session: Session, capsys) -> None:
    assert script.main([], session_factory=session_factory(db_session)) == 0

    out = capsys.readouterr().out
    assert "products           created   50" in out
    assert "Password: Demo-pass-123" in out


def test_missing_tables_give_a_helpful_message(script: ModuleType, tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    with Session(engine) as empty_db, pytest.raises(script.SeedError, match="alembic upgrade"):
        script.seed(empty_db)
    engine.dispose()


def test_seeded_stock_fits_its_bins_and_is_traceable(
    script: ModuleType, db_session: Session
) -> None:
    script.seed(db_session)
    inventory = InventoryService(db_session)

    rows = list(db_session.scalars(select(Inventory)))
    assert len({row.bin_id for row in rows}) == len(rows)  # one product per bin
    for row in rows:
        weight, volume = inventory.bin_load(row.bin_id)
        assert weight <= row.bin.max_weight_kg and volume <= row.bin.max_volume_cm3
    chilled = {
        r.bin.location_code.split("-")[1]
        for r in rows
        if r.product.sku.startswith("FOO-") and r.product.sku in script.CHILLED_SKUS
    }
    assert chilled == {"ZC"}
    # Every unit is explained by a receipt movement
    received = db_session.scalar(select(func.sum(InventoryMovement.on_hand_delta)))
    assert received == sum(row.quantity_on_hand for row in rows)


def test_seed_raises_exactly_the_planned_low_stock_alerts(
    script: ModuleType, db_session: Session
) -> None:
    script.seed(db_session)

    low = select(Alert).where(Alert.alert_type == "low_stock")
    alerts = {a.title.removeprefix("Low stock: "): a for a in db_session.scalars(low)}
    assert set(alerts) == script.LOW_STOCK_SKUS | script.OUT_OF_STOCK_SKUS
    assert {a.status for a in alerts.values()} == {"open"}  # none raised and resolved again
    assert alerts["TOO-LAD1"].severity == "critical"
    pending = db_session.scalars(select(StockAdjustment)).one()
    assert (pending.status, pending.kind, pending.quantity) == ("pending", "damage", 2)


def test_reset_removes_stock_but_keeps_movements_protected(
    script: ModuleType, db_session: Session
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    script.seed(db_session)

    script.reset(db_session)

    for model in (Inventory, InventoryMovement, StockAdjustment, Alert):
        assert count(db_session, model) == 0
    script.seed(db_session)  # and it can be loaded again
    with pytest.raises(IntegrityError, match="immutable"):
        db_session.execute(text("DELETE FROM inventory_movements"))
    db_session.rollback()


def test_reset_also_removes_orders_and_picking(script: ModuleType, db_session: Session) -> None:
    from app.models.fulfillment import PickingTask
    from app.models.order import Order
    from app.schemas.order import OrderCreate
    from app.services.fulfillment_service import FulfillmentService
    from app.services.order_service import OrderService
    from tests.factories import create_customer

    script.seed(db_session)
    customer = create_customer(db_session, "CUST-9999")
    product = db_session.scalars(select(Product).where(Product.sku == "LAP-1401")).one()
    orders = OrderService(db_session)
    order = orders.create(
        OrderCreate(customer_id=customer.id, items=[{"product_id": product.id, "quantity": 2}]),
        user=None,
    )
    orders.confirm(order.id, user=None)
    FulfillmentService(db_session).allocate(order.id, user=None)

    script.reset(db_session)

    assert count(db_session, Order) == 0
    assert count(db_session, PickingTask) == 0
    assert count(db_session, Product) == 0


def test_demo_orders_reach_their_stages(script: ModuleType, db_session: Session) -> None:
    from app.models.order import Customer, Order

    script.seed(db_session)

    statuses = [o.status for o in db_session.scalars(select(Order).order_by(Order.id))]
    assert statuses == [
        "returned",
        "shipped",
        "delayed",
        "picking",
        "inventory_reserved",
        "backordered",
        "created",
    ]
    chris = db_session.scalars(select(Customer).where(Customer.code == "CUST-0001")).one()
    assert chris.user.email == "customer@example.com"
    delay = db_session.scalars(select(Alert).where(Alert.alert_type == "delay_risk")).one()
    assert delay.status == "open"


def test_demo_purchase_orders(script: ModuleType, db_session: Session) -> None:
    from app.models.purchase import PurchaseOrder

    script.seed(db_session)

    pos = db_session.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id)).all()
    assert [(p.supplier.code, p.status, p.is_overdue) for p in pos] == [
        ("SUP-004", "ordered", True),
        ("SUP-010", "ordered", False),
        ("SUP-009", "draft", False),
    ]
    overdue = db_session.scalars(select(Alert).where(Alert.alert_type == "overdue_supplier")).one()
    assert overdue.dedup_key == f"overdue_supplier:po:{pos[0].id}"
    assert f"{script.OVERDUE_DAYS} day(s) late" in overdue.message
    assert script.seed(db_session).skipped["purchase orders"] == 3

    script.reset(db_session)
    assert count(db_session, PurchaseOrder) == 0
