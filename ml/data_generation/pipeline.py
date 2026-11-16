"""The whole generation in the order of the project document (section 11.3).

Used by `scripts/generate_data.py` (one command for everything) and by the tests::

    database (migrated, empty)  ->  master data  ->  warehouse layout
    ->  two years, day by day: purchasing, shipping, orders, fulfillment, housekeeping
    ->  alerts as the application would show them on the last day

Data is written in batches while the simulation runs, so memory stays manageable.
"""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.audit import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.catalog import Product
from app.models.order import Order, OrderStatus
from app.models.shipment import Shipment
from app.models.warehouse import Bin
from app.services.alert_service import AlertService, delay_key
from app.services.purchase_order_service import PurchaseOrderService
from data_generation.config import DatasetConfig
from data_generation.context import GenerationContext
from data_generation.database import BatchWriter, prepare_database
from data_generation.generate_fulfillment import FulfillmentProcess, HousekeepingProcess
from data_generation.generate_master_data import generate_master_data
from data_generation.generate_orders import OrderBook, OrdersProcess
from data_generation.generate_purchasing import PurchasingProcess
from data_generation.generate_shipments import ShipmentsProcess
from data_generation.generate_warehouse_layout import generate_warehouse_layout
from data_generation.simulation import Simulation

Reporter = Callable[[str], None]


def _quiet(_message: str) -> None:
    pass


@dataclass
class Generated:
    ctx: GenerationContext
    engine: Engine
    processes: dict[str, Any] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)


def build(config: DatasetConfig, path: Path, *, replace: bool = False) -> GenerationContext:
    """A new database with master data and the warehouse layout."""
    engine = prepare_database(path, replace=replace)
    ctx = GenerationContext(config=config, writer=BatchWriter(engine, config.batch_size))
    generate_master_data(ctx)
    generate_warehouse_layout(ctx)
    return ctx


def simulate(ctx: GenerationContext, *, report: Reporter = _quiet) -> dict[str, Any]:
    """Two years of operations, day by day; reports one line per simulated month."""
    sim = Simulation(ctx)
    book = OrderBook(ctx)
    purchasing = PurchasingProcess(ctx)
    orders = OrdersProcess(ctx, book)
    shipping = ShipmentsProcess(ctx, book)
    fulfillment = FulfillmentProcess(ctx, book, shipping)
    housekeeping = HousekeepingProcess(ctx)
    last = ctx.config.days - 1
    started = time.perf_counter()

    def after_day(day: date, day_index: int) -> None:
        if (day + timedelta(days=1)).day == 1 or day_index == last:  # end of a month
            report(
                f"  {day:%Y-%m}  {book.count:>9,} orders  {len(purchasing.orders):>7,} purchase "
                f"orders  ({day_index + 1}/{ctx.config.days} days, "
                f"{time.perf_counter() - started:.0f}s)"
            )

    sim.run([purchasing, shipping, orders, fulfillment, housekeeping], after_day=after_day)
    book.finish()
    return {
        "sim": sim,
        "book": book,
        "orders": orders,
        "purchasing": purchasing,
        "shipping": shipping,
        "fulfillment": fulfillment,
        "housekeeping": housekeeping,
    }


def raise_alerts(engine: Engine, today: date) -> Counter[str]:
    """The alerts the application raises itself, as of the last simulated day: low stock,
    bins over capacity, delayed shipments and overdue purchase orders."""
    with Session(engine) as db:
        alerts = AlertService(db)
        alerts.evaluate(
            product_ids=db.scalars(select(Product.id)).all(),
            bin_ids=db.scalars(select(Bin.id)).all(),
        )
        delayed = db.execute(
            select(Order, Shipment)
            .join(Shipment, Shipment.order_id == Order.id)
            .where(Order.status == OrderStatus.DELAYED)
            .order_by(Order.id)
        ).all()
        for order, shipment in delayed:  # as the shipment service does for a delay event
            alerts.raise_alert(
                AlertType.DELAY_RISK,
                delay_key(order.id),
                severity=AlertSeverity.WARNING,
                title=f"Delayed: {order.order_number}",
                message=(
                    f"{shipment.carrier.code} {shipment.tracking_number}, expected "
                    f"{shipment.expected_delivery_date.isoformat()}"
                ),
                warehouse_id=order.warehouse_id,
            )
        db.commit()
        PurchaseOrderService(db).check_overdue(today=today)
        rows = db.execute(
            select(Alert.alert_type, func.count())
            .where(Alert.status != AlertStatus.RESOLVED)
            .group_by(Alert.alert_type)
        ).all()
    return Counter({str(kind): count for kind, count in rows})


def generate(
    config: DatasetConfig,
    path: Path,
    *,
    replace: bool = False,
    report: Reporter = _quiet,
    stages: int = 3,
) -> Generated:
    """Everything: database, master data, layout, two years of history and alerts."""
    seconds: dict[str, float] = {}

    def stage(name: str, number: int) -> float:
        report(f"[{number}/{stages}] {name}")
        return time.perf_counter()

    started = stage("Database, master data and warehouse layout", 1)
    ctx = build(config, path, replace=replace)
    seconds["master data and layout"] = time.perf_counter() - started
    report(
        f"  {len(ctx.products):,} products, {len(ctx.suppliers):,} suppliers, "
        f"{len(ctx.customers):,} customers, {len(ctx.bins):,} bins"
    )

    started = stage(f"Simulating {config.days} days ({config.start_date} to {config.end_date})", 2)
    processes = simulate(ctx, report=report)
    seconds["simulation"] = time.perf_counter() - started

    started = stage("Alerts on the last day", 3)
    engine = ctx.writer.engine
    alerts = raise_alerts(engine, config.end_date)
    seconds["alerts"] = time.perf_counter() - started
    report("  " + (", ".join(f"{n:,} {kind}" for kind, n in sorted(alerts.items())) or "none"))
    processes["alerts"] = alerts
    return Generated(ctx=ctx, engine=engine, processes=processes, seconds=seconds)
