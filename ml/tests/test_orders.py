"""Two years of customer orders on the small dataset (picking and shipping are a
stand-in until Step 5, see tests/conftest.py)."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.models import Order
from app.schemas.order import OrderCreate
from app.services.dashboard_service import DashboardService, DateRange
from app.services.order_service import OrderService, can_transition
from data_generation.context import GenerationContext
from data_generation.generate_orders import OrderBook, OrdersProcess, SimLine
from data_generation.patterns import black_friday
from data_generation.simulation import Simulation, at

Simulated = tuple[GenerationContext, Engine, dict]


def rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql))]


def parse(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- volume
def test_order_volume_matches_the_configuration(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    (count,) = rows(engine, "SELECT COUNT(*) FROM orders")[0]
    assert count == pytest.approx(ctx.config.orders, rel=0.12)
    units = rows(engine, "SELECT SUM(quantity), COUNT(*) FROM order_items GROUP BY order_id")
    assert 3.5 < mean(u for u, _ in units) < 5.0  # about 4 units ...
    assert 2.0 < mean(n for _, n in units) < 3.0  # ... on about 2.5 lines per order


def test_orders_are_numbered_and_priced_consistently(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    numbers = [r[0] for r in rows(engine, "SELECT order_number FROM orders")]
    per_year = defaultdict(list)
    for number in numbers:
        _, year, sequence = number.split("-")
        per_year[year].append(int(sequence))
    for sequences in per_year.values():
        assert sorted(sequences) == list(range(1, len(sequences) + 1))
    wrong_total = rows(
        engine,
        "SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id "
        "GROUP BY o.id HAVING SUM(i.quantity * i.unit_price) != o.subtotal",
    )
    assert wrong_total == []
    wrong_lines = rows(
        engine,
        "SELECT order_id FROM order_items GROUP BY order_id "
        "HAVING MIN(line_number) != 1 OR MAX(line_number) != COUNT(*)",
    )
    assert wrong_lines == []


def test_ship_to_comes_from_the_customer(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    wrong = rows(
        engine,
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.id = o.customer_id "
        "WHERE o.ship_to_name IS NOT c.name OR o.ship_to_city IS NOT c.city "
        "OR o.ship_to_postal_code IS NOT c.postal_code",
    )
    assert wrong == [(0,)]


# ------------------------------------------------------------------------ lifecycle
def test_every_status_change_is_allowed_by_the_application(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    history = defaultdict(list)
    for order_id, before, after, when in rows(
        engine,
        "SELECT order_id, from_status, to_status, created_at FROM order_status_history "
        "ORDER BY order_id, id",
    ):
        history[order_id].append((before, after, parse(when)))
    final = dict(rows(engine, "SELECT id, status FROM orders"))
    assert set(history) == set(final)
    for order_id, entries in history.items():
        assert entries[0][:2] == (None, "created")
        for (_, previous, at_before), (before, after, moment) in zip(
            entries, entries[1:], strict=False
        ):
            assert before == previous
            assert can_transition(before, after), (order_id, before, after)
            assert moment >= at_before
        assert entries[-1][1] == final[order_id]


def test_milestone_times_match_the_history(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    mismatches = rows(
        engine,
        "SELECT o.id FROM orders o JOIN order_status_history h ON h.order_id = o.id "
        "WHERE (h.to_status = 'confirmed' AND h.created_at != o.confirmed_at) "
        "OR (h.to_status = 'delivered' AND h.created_at != o.delivered_at) "
        "OR (h.to_status = 'cancelled' AND h.created_at != o.cancelled_at)",
    )
    assert mismatches == []


def test_reservations_match_the_stock(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    mismatches = rows(
        engine,
        "SELECT i.product_id, i.bin_id FROM inventory i LEFT JOIN ("
        "  SELECT product_id, bin_id, SUM(quantity) AS held FROM stock_reservations "
        "  WHERE status = 'active' GROUP BY product_id, bin_id) r "
        "ON r.product_id = i.product_id AND r.bin_id = i.bin_id "
        "WHERE COALESCE(r.held, 0) != i.quantity_reserved",
    )
    assert mismatches == []
    orphans = rows(
        engine,
        "SELECT COUNT(*) FROM stock_reservations r LEFT JOIN orders o ON o.id = r.reference_id "
        "WHERE r.reference_type != 'order' OR o.id IS NULL",
    )
    assert orphans == [(0,)]


def test_order_lines_know_what_is_reserved_for_them(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    mismatches = rows(
        engine,
        "SELECT i.order_id, i.product_id FROM order_items i "
        "JOIN orders o ON o.id = i.order_id LEFT JOIN ("
        "  SELECT reference_id, product_id, SUM(quantity) AS held FROM stock_reservations "
        "  WHERE status != 'released' GROUP BY reference_id, product_id) r "
        "ON r.reference_id = i.order_id AND r.product_id = i.product_id "
        "WHERE o.status != 'cancelled' AND COALESCE(r.held, 0) != i.quantity_reserved",
    )
    assert mismatches == []


def test_waiting_orders_get_their_stock_later(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    waited = rows(
        engine,
        "SELECT COUNT(DISTINCT order_id) FROM order_status_history "
        "WHERE to_status IN ('backordered', 'partially_allocated')",
    )[0][0]
    filled = rows(
        engine,
        "SELECT COUNT(DISTINCT order_id) FROM order_status_history "
        "WHERE from_status IN ('backordered', 'partially_allocated') "
        "AND to_status = 'inventory_reserved'",
    )[0][0]
    (count,) = rows(engine, "SELECT COUNT(*) FROM orders")[0]
    assert 0.03 < waited / count < 0.35
    assert filled > 0.6 * waited


def test_cancelled_orders_hold_nothing(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    cancelled = rows(
        engine, "SELECT id, cancel_reason, cancelled_at FROM orders WHERE status = 'cancelled'"
    )
    assert cancelled
    assert all(reason and moment for _, reason, moment in cancelled)
    held = rows(
        engine,
        "SELECT COUNT(*) FROM stock_reservations r JOIN orders o ON o.id = r.reference_id "
        "WHERE o.status = 'cancelled' AND r.status != 'released'",
    )
    assert held == [(0,)]
    reserved = rows(
        engine,
        "SELECT SUM(i.quantity_reserved) FROM order_items i JOIN orders o ON o.id = i.order_id "
        "WHERE o.status = 'cancelled'",
    )
    assert reserved == [(0,)]


# ------------------------------------------------------------------------- patterns
def orders_by_day(engine: Engine) -> dict[date, int]:
    return {
        date.fromisoformat(day): count
        for day, count in rows(
            engine, "SELECT DATE(created_at), COUNT(*) FROM orders GROUP BY DATE(created_at)"
        )
    }


def test_weekly_and_yearly_patterns(busy: Simulated) -> None:
    _, engine, _ = busy
    weekday = defaultdict(int)
    month = defaultdict(int)
    for day, count in orders_by_day(engine).items():
        weekday[day.weekday()] += count
        month[day.month] += count
    assert weekday[6] < 0.6 * mean(weekday[d] for d in range(5))  # quiet Sundays
    assert month[12] > 1.3 * month[2]  # Christmas


def test_black_friday_weekend_is_busy(busy: Simulated) -> None:
    _, engine, _ = busy
    by_day = orders_by_day(engine)
    friday = black_friday(2025)
    peak = sum(by_day.get(friday + timedelta(days=i), 0) for i in range(4))
    october = [by_day.get(date(2025, 10, d), 0) for d in range(3, 31)]
    assert peak / 4 > 1.7 * mean(october)
    assert by_day.get(date(2025, 12, 25), 0) < 0.3 * mean(october)


def test_companion_products_are_bought_together(busy: Simulated) -> None:
    """The recommendation use case needs product pairs: a laptop's companions (e.g. its
    mouse and bag) appear with it far more often than in a random order."""
    _, engine, extra = busy
    rules = extra["orders"].basket_rules
    products = {i: p.id for i, p in enumerate(extra["orders"].products)}
    baskets = defaultdict(set)
    for order_id, product_id in rows(engine, "SELECT order_id, product_id FROM order_items"):
        baskets[order_id].add(product_id)
    orders = list(baskets.values())
    lifts = []
    for anchor, companions in rules.items():
        with_anchor = [b for b in orders if products[anchor] in b]
        if len(with_anchor) < 30:
            continue
        for companion in companions:
            together = mean(products[companion] in b for b in with_anchor)
            anywhere = mean(products[companion] in b for b in orders)
            lifts.append(together / anywhere)
    assert len(lifts) > 10
    assert mean(lifts) > 3


def test_a_few_customers_order_a_lot(busy: Simulated) -> None:
    ctx, engine, _ = busy
    counts = sorted(
        (c for _, c in rows(engine, "SELECT customer_id, COUNT(*) FROM orders GROUP BY 1")),
        reverse=True,
    )
    top_tenth = sum(counts[: len(ctx.customers) // 10]) / sum(counts)
    assert top_tenth > 0.25


def test_promotions_lower_the_price(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    products = {p.id: p for p in ctx.products}
    discounted = 0
    for product_id, price, created in rows(
        engine,
        "SELECT i.product_id, i.unit_price, o.created_at FROM order_items i "
        "JOIN orders o ON o.id = i.order_id",
    ):
        product = products[product_id]
        on_promotion = product.profile.promotion_factor(parse(created).date()) > 1
        expected = product.unit_price
        if on_promotion:
            expected = (expected * Decimal("0.85")).quantize(Decimal("0.01"))
            discounted += 1
        assert price == int(expected * 100)  # stored in cents
    assert discounted > 0


# ------------------------------------------------------------ choosing the warehouse
def test_warehouse_choice(tmp_path: Path, builder: Callable) -> None:
    ctx, _ = builder(tmp_path / "three.db", warehouses=3)
    sim = Simulation(ctx)
    process = OrdersProcess(ctx, OrderBook(ctx))
    process.on_start(sim)
    customer = next(c for c in ctx.customers if process.home[c.id] != 1)
    home = process.home[customer.id]
    other = next(w for w in ctx.warehouse_ids if w != home)
    a, b = [p for p in ctx.products if p.storage == "picking"][:2]
    when = at(ctx.config.start_date, 8)

    def order(*lines: tuple[int, int]) -> object:
        return process.book.new_order(
            customer,
            [SimLine(i + 1, pid, qty, Decimal(1)) for i, (pid, qty) in enumerate(lines)],
            when,
            priority="normal",
            requested=None,
        )

    assert process.choose_warehouse(sim, order((a.id, 2))) is None  # no stock anywhere
    sim.ledger.receive(a.id, other, 5, when, reason="x")
    assert process.choose_warehouse(sim, order((a.id, 2))) == other  # only there
    sim.ledger.receive(a.id, 1, 5, when, reason="x")
    sim.ledger.receive(a.id, home, 5, when, reason="x")
    assert process.choose_warehouse(sim, order((a.id, 2))) == home  # a tie: home wins
    sim.ledger.receive(b.id, other, 5, when, reason="x")
    assert process.choose_warehouse(sim, order((a.id, 2), (b.id, 3))) == other  # covers more


def test_reservations_prefer_picking_zones_close_to_packing(
    tmp_path: Path, builder: Callable
) -> None:
    """Six zones: picking A (5 m), bulk (60 m), cold, hazardous, picking B (30 m), returns
    (10 m). Picking first, then distance; bin ids or distance alone give other orders."""
    ctx, _ = builder(tmp_path / "bins.db", zones_per_warehouse=6)
    ledger = Simulation(ctx).ledger
    product = next(p for p in ctx.products if p.storage == "picking")

    def nearest(zone_type: str, beyond: float = 0) -> object:
        return min(
            (b for b in ctx.bins if b.zone_type == zone_type and b.distance_m >= beyond),
            key=lambda b: (b.distance_m, b.id),
        )

    picking_a, picking_b = nearest("picking"), nearest("picking", beyond=30)
    returns, bulk = nearest("returns"), nearest("bulk")
    assert returns.distance_m < picking_b.distance_m < bulk.distance_m
    assert bulk.id < picking_b.id < returns.id
    when = at(ctx.config.start_date, 8)
    for bin_ in (bulk, returns, picking_b, picking_a):  # stock put there directly
        ledger._change(product, bin_.id, 1, "receipt", 2, 2, 0, 0, when, "x")
    made = ledger.reserve(product.id, 1, 7, when, order_id=1, reason="x")
    assert [r.bin_id for r in made] == [picking_a.id, picking_b.id, returns.id, bulk.id]
    assert [r.quantity for r in made] == [2, 2, 2, 1]


def test_reservation_status_and_priority(tmp_path: Path, builder: Callable) -> None:
    ctx, _ = builder(tmp_path / "status.db")
    sim = Simulation(ctx)
    book = OrderBook(ctx)
    process = OrdersProcess(ctx, book)
    process.on_start(sim)
    a, b = [p for p in ctx.products if p.storage == "picking"][:2]
    customer = ctx.customers[0]
    when = at(ctx.config.start_date, 8)

    def place(priority: str, *lines: tuple[int, int]) -> object:
        order = book.new_order(
            customer,
            [SimLine(i + 1, pid, qty, Decimal(1)) for i, (pid, qty) in enumerate(lines)],
            when,
            priority=priority,
            requested=None,
        )
        book.transition(order, "confirmed", when)
        process.reserve(sim, order, when)
        return order

    sim.ledger.receive(a.id, 1, 3, when, reason="x")
    complete = place("normal", (a.id, 1))
    partly = place("normal", (a.id, 1), (b.id, 2))
    old = place("normal", (b.id, 1))
    newer = place("normal", (b.id, 1))
    urgent = place("urgent", (b.id, 1))
    assert complete.status == "inventory_reserved"
    assert partly.status == "partially_allocated"
    assert partly.history[-1][3] == "1 of 3 units reserved"
    assert old.status == newer.status == urgent.status == "backordered"

    sim.ledger.receive(b.id, 1, 2, when, reason="x")  # two units arrive
    process._retry_waiting(sim, ctx.config.start_date)
    assert urgent.status == "inventory_reserved"  # urgent first, though the newest
    assert partly.lines[1].reserved == 1  # then the oldest waiting order
    assert partly.status == "partially_allocated"  # (it needs 2)
    assert old.status == newer.status == "backordered"


def test_long_waits_lead_to_cancellations(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    reasons = [
        r[0]
        for r in rows(engine, "SELECT cancel_reason FROM orders WHERE cancel_reason IS NOT NULL")
    ]
    waited = [int(r.split()[-2]) for r in reasons if "after waiting" in r]
    assert waited and min(waited) >= 7
    assert any(r == "Customer changed their mind" for r in reasons)


# ------------------------------------------------------------------- the application
def test_the_application_can_work_with_the_generated_orders(
    tmp_path: Path, order_simulator: Callable
) -> None:
    """On its own copy: the test changes the data."""
    ctx, engine, _ = order_simulator(tmp_path / "app.db")
    end = ctx.config.end_date
    start = end - timedelta(days=89)
    with Session(engine) as session:
        dashboard = DashboardService(session).fulfillment(DateRange(start, end))
        placed = session.scalar(
            select(func.count(Order.id)).where(
                Order.created_at >= datetime.combine(start, time.min, tzinfo=UTC)
            )
        )
        assert dashboard.totals.placed == placed > 0

        # The application's own services continue on the generated data.
        product_id, reserved_before = session.execute(
            text(
                "SELECT product_id, SUM(quantity_reserved) FROM inventory GROUP BY product_id "
                "ORDER BY SUM(quantity_on_hand - quantity_reserved - quantity_damaged) DESC "
                "LIMIT 1"
            )
        ).one()
        service = OrderService(session)
        order = service.create(
            OrderCreate(customer_id=1, items=[{"product_id": product_id, "quantity": 2}]),
            user=None,
        )
        service.confirm(order.id, user=None)
        assert order.status == "inventory_reserved"
        service.cancel(order.id, user=None, reason="test")
        reserved_after = session.scalar(
            text("SELECT SUM(quantity_reserved) FROM inventory WHERE product_id = :p"),
            {"p": product_id},
        )
        assert reserved_after == reserved_before


def test_orders_are_reproducible(
    tmp_path: Path, with_orders: Simulated, order_simulator: Callable
) -> None:
    _, first, _ = with_orders
    _, again, _ = order_simulator(tmp_path / "again.db")
    for query in (
        "SELECT * FROM orders ORDER BY id",
        "SELECT * FROM order_items ORDER BY order_id, line_number",
        "SELECT * FROM stock_reservations ORDER BY id",
    ):
        assert rows(again, query) == rows(first, query)
