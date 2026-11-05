"""Tests for automatic low-stock and over-capacity alerts."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.models.audit import Alert, AlertStatus
from app.models.catalog import Product
from app.models.inventory import AdjustmentKind
from app.models.user import RoleName
from app.models.warehouse import Bin
from app.schemas.catalog import ProductUpdate
from app.schemas.inventory import (
    AdjustmentRequest,
    CycleCountRecord,
    CycleCountStart,
    ReceiveRequest,
    ReserveRequest,
)
from app.schemas.warehouse import BinUpdate
from app.services.alert_service import AlertService
from app.services.catalog_service import ProductService
from app.services.cycle_count_service import CycleCountService
from app.services.inventory_service import InventoryService
from app.services.warehouse_service import WarehouseService
from tests.factories import create_bin, create_category, create_product, create_user


@pytest.fixture()
def product(db_session: Session) -> Product:
    return create_product(db_session, create_category(db_session), sku="LAP-001", min_stock=5)


@pytest.fixture()
def bin_(db_session: Session) -> Bin:
    return create_bin(db_session, max_weight_kg="20.000")


@pytest.fixture()
def inventory(db_session: Session) -> InventoryService:
    return InventoryService(db_session)


def alerts(db: Session, status: str | None = None) -> list[Alert]:
    query = select(Alert).order_by(Alert.id)
    if status:
        query = query.where(Alert.status == status)
    return list(db.scalars(query))


def receive(inventory: InventoryService, product: Product, bin_: Bin, quantity: int) -> None:
    inventory.receive(
        ReceiveRequest(product_id=product.id, bin_id=bin_.id, quantity=quantity), user=None
    )


def decrease(inventory: InventoryService, product: Product, bin_: Bin, quantity: int) -> None:
    inventory.adjust(
        AdjustmentRequest(
            product_id=product.id,
            bin_id=bin_.id,
            kind=AdjustmentKind.DECREASE,
            quantity=quantity,
            reason="Lost",
        ),
        user=None,
    )


# ------------------------------------------------------------------------ low stock
def test_low_stock_is_raised_updated_and_resolved_automatically(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 3)  # below the minimum of 5
    [alert] = alerts(db_session)
    assert (alert.alert_type, alert.severity, alert.status) == ("low_stock", "warning", "open")
    assert alert.title == "Low stock: LAP-001"
    assert alert.message == "Product LAP-001: 3 available, minimum stock is 5."
    assert alert.product_id == product.id

    decrease(inventory, product, bin_, 3)  # nothing left: same alert, now critical
    [alert] = alerts(db_session)
    assert alert.severity == "critical"
    assert "0 available" in alert.message

    receive(inventory, product, bin_, 6)  # back above the minimum
    [alert] = alerts(db_session)
    assert alert.status == AlertStatus.RESOLVED
    assert alert.resolved_at is not None and alert.resolved_by_id is None  # the system

    decrease(inventory, product, bin_, 2)  # low again: a NEW alert, history is kept
    assert [a.status for a in alerts(db_session)] == ["resolved", "open"]


def test_reservations_count_as_unavailable(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 8)
    assert alerts(db_session) == []

    inventory.reserve(ReserveRequest(product_id=product.id, quantity=4), user=None)

    [alert] = alerts(db_session, "open")
    assert "4 available" in alert.message


def test_stock_in_archived_bins_does_not_count(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 10)

    WarehouseService(db_session).update(bin_, BinUpdate(is_active=False))

    [alert] = alerts(db_session, "open")
    assert alert.severity == "critical"


def test_no_alert_without_a_minimum_or_for_archived_products(
    db_session: Session, inventory: InventoryService, bin_: Bin
):
    category = create_category(db_session, "Toys")
    no_minimum = create_product(db_session, category, sku="TOY-001", min_stock=0)
    receive(inventory, no_minimum, bin_, 1)
    assert alerts(db_session) == []

    low = create_product(db_session, category, sku="TOY-002", min_stock=10)
    receive(inventory, low, bin_, 1)
    assert len(alerts(db_session, "open")) == 1

    ProductService(db_session).update(low.id, ProductUpdate(is_active=False))
    assert alerts(db_session, "open") == []  # archived products are not reordered


def test_changing_the_minimum_raises_or_resolves(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 6)
    products = ProductService(db_session)

    products.update(product.id, ProductUpdate(min_stock=10))
    assert len(alerts(db_session, "open")) == 1

    products.update(product.id, ProductUpdate(min_stock=2))
    assert alerts(db_session, "open") == []


# --------------------------------------------------------------------- over capacity
def test_bin_over_capacity_after_its_limit_was_lowered(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 15)  # 15 kg of 20 kg

    WarehouseService(db_session).update(bin_, BinUpdate(max_weight_kg=Decimal("10.000")))

    [alert] = alerts(db_session, "open")
    assert alert.alert_type == "over_capacity"
    assert alert.title == "Bin over capacity: WH01-ZA-R01-S01-B01"
    assert alert.message == ("Contents exceed the bin limits: weight 15.000 kg of max 10.000 kg.")
    assert (alert.bin_id, alert.warehouse_id) == (bin_.id, bin_.shelf.rack.zone.warehouse_id)

    decrease(inventory, product, bin_, 6)  # 9 kg: fits again
    assert alerts(db_session, "open") == []


def test_cycle_count_finding_more_units_can_overfill_a_bin(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    receive(inventory, product, bin_, 18)
    counts = CycleCountService(db_session)
    count = counts.start(CycleCountStart(bin_id=bin_.id), user=None)
    counts.record(
        count.id,
        CycleCountRecord(lines=[{"product_id": product.id, "counted_quantity": 23}]),
        user=None,
    )
    counts.submit(count.id, user=None)

    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    counts.approve(count.id, approver=manager)

    [alert] = alerts(db_session, "open")
    assert alert.alert_type == "over_capacity"


# -------------------------------------------------------------------- people actions
def test_acknowledge_and_resolve_by_hand(
    db_session: Session, inventory: InventoryService, product: Product, bin_: Bin
):
    manager = create_user(db_session, "manager@example.com", roles=(RoleName.MANAGER,))
    service = AlertService(db_session)
    receive(inventory, product, bin_, 2)
    [alert] = alerts(db_session)

    service.acknowledge(alert.id, user=manager)
    assert (alert.status, alert.acknowledged_by_id) == ("acknowledged", manager.id)
    with pytest.raises(ConflictError, match="already acknowledged"):
        service.acknowledge(alert.id, user=manager)

    # An acknowledged alert is still kept up to date (no second alert)
    decrease(inventory, product, bin_, 1)
    assert len(alerts(db_session)) == 1
    assert "1 available" in alert.message

    service.resolve(alert.id, user=manager)
    assert (alert.status, alert.resolved_by_id) == ("resolved", manager.id)
    with pytest.raises(ConflictError, match="already resolved"):
        service.resolve(alert.id, user=manager)

    # Still low: the next change raises a fresh alert
    decrease(inventory, product, bin_, 1)
    assert [a.status for a in alerts(db_session)] == ["resolved", "open"]
    assert service.count_unresolved() == 1


def test_bulk_loading_can_defer_alerts(db_session: Session, product: Product, bin_: Bin):
    loader = InventoryService(db_session, update_alerts=False)
    receive(loader, product, bin_, 1)
    receive(loader, product, bin_, 1)
    assert alerts(db_session) == []

    AlertService(db_session).evaluate(product_ids=[product.id])
    assert len(alerts(db_session, "open")) == 1
