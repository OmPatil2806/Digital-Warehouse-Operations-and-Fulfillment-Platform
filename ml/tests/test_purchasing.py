"""Opening stock, reordering and deliveries over two simulated years (small dataset).

Demand comes from a stand-in process (tests/conftest.py) until customer orders are
generated in Step 4.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.dashboard_service import DashboardService, DateRange
from data_generation.context import GenerationContext
from data_generation.generate_purchasing import (
    PUBLIC_HOLIDAYS,
    OrderLine,
    PurchasingProcess,
    is_working_day,
    next_working_day,
)
from data_generation.patterns import is_peak_season
from data_generation.simulation import TRACKING_DAYS, DemandTracker, Simulation, at
from data_generation.stock import HEAVY_KG, StockLedger

Simulated = tuple[GenerationContext, Engine, dict]


def rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql))]


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parse(value: str) -> datetime:
    return as_utc(datetime.fromisoformat(value))


# ------------------------------------------------------------------------ stock rules
def test_stock_never_breaks_the_rules(simulated: Simulated) -> None:
    _, engine, _ = simulated
    bad = rows(
        engine,
        "SELECT COUNT(*) FROM inventory WHERE quantity_on_hand < 0 OR quantity_reserved < 0 "
        "OR quantity_damaged < 0 OR quantity_reserved + quantity_damaged > quantity_on_hand",
    )
    assert bad == [(0,)]
    over = rows(
        engine,
        "SELECT b.location_code FROM inventory i JOIN products p ON p.id = i.product_id "
        "JOIN bins b ON b.id = i.bin_id GROUP BY b.id "
        "HAVING SUM(i.quantity_on_hand * p.weight_kg) > b.max_weight_kg "
        "OR SUM(i.quantity_on_hand * p.length_cm * p.width_cm * p.height_cm) "
        "> b.max_volume_cm3 * 1000",  # weights in grams, lengths in mm: cm³ x 1000
    )
    assert over == []


def test_every_unit_is_explained_by_movements(simulated: Simulated) -> None:
    _, engine, _ = simulated
    mismatches = rows(
        engine,
        "SELECT i.product_id, i.bin_id FROM inventory i LEFT JOIN ("
        "  SELECT product_id, bin_id, SUM(on_hand_delta) AS total FROM inventory_movements "
        "  GROUP BY product_id, bin_id) m ON m.product_id = i.product_id AND m.bin_id = i.bin_id "
        "WHERE COALESCE(m.total, 0) != i.quantity_on_hand",
    )
    assert mismatches == []
    # Each movement's "after" balance continues from the previous one in its bin.
    balances: dict[tuple[int, int], int] = defaultdict(int)
    for product_id, bin_id, delta, after in rows(
        engine,
        "SELECT product_id, bin_id, on_hand_delta, on_hand_after FROM inventory_movements "
        "ORDER BY id",
    ):
        balances[(product_id, bin_id)] += delta
        assert balances[(product_id, bin_id)] == after


def test_opening_stock_on_the_first_morning(simulated: Simulated) -> None:
    ctx, engine, _ = simulated
    opening = rows(
        engine,
        "SELECT product_id, MIN(created_at), MAX(created_at) FROM inventory_movements "
        "WHERE reason = 'Opening stock' GROUP BY product_id",
    )
    assert len(opening) == len(ctx.products)
    first_morning = at(ctx.config.start_date, 6.0)
    assert all(parse(a) == parse(b) == first_morning for _, a, b in opening)


# ------------------------------------------------------------------- purchase orders
def test_purchase_orders_are_consistent(simulated: Simulated) -> None:
    ctx, engine, extra = simulated
    orders = rows(
        engine,
        "SELECT po.po_number, po.status, po.ordered_at, po.received_at, po.expected_date, "
        "s.lead_time_days, SUM(i.quantity), SUM(i.quantity_received) "
        "FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id "
        "JOIN purchase_order_items i ON i.purchase_order_id = po.id GROUP BY po.id",
    )
    assert len(orders) == len(extra["purchasing"].orders) > len(ctx.products)
    numbers = [o[0] for o in orders]
    assert len(set(numbers)) == len(numbers)
    for number, status, ordered, received, expected, lead, quantity, got in orders:
        ordered_at = parse(ordered)
        assert is_working_day(ordered_at.date()), number
        assert date.fromisoformat(expected) == ordered_at.date() + timedelta(days=lead)
        if status == "received":
            assert got == quantity
            received_at = parse(received)
            assert received_at > ordered_at
            assert is_working_day(received_at.date())
        elif status == "partially_received":
            assert 0 < got < quantity and received is None
        else:
            assert status == "ordered" and got == 0 and received is None
    years = defaultdict(list)
    for number in numbers:
        _, year, sequence = number.split("-")
        years[year].append(int(sequence))
    for sequences in years.values():
        assert sorted(sequences) == list(range(1, len(sequences) + 1))


def test_open_orders_are_the_recent_ones(simulated: Simulated) -> None:
    ctx, engine, _ = simulated
    open_dates = [
        parse(r[0]).date()
        for r in rows(engine, "SELECT ordered_at FROM purchase_orders WHERE status != 'received'")
    ]
    assert open_dates  # some are still on their way at the end of the history
    assert min(open_dates) > ctx.config.end_date - timedelta(days=70)


def test_lines_are_ordered_from_the_products_suppliers_at_their_prices(
    simulated: Simulated,
) -> None:
    _, engine, _ = simulated
    wrong = rows(
        engine,
        "SELECT COUNT(*) FROM purchase_order_items i "
        "JOIN purchase_orders po ON po.id = i.purchase_order_id "
        "LEFT JOIN supplier_products sp ON sp.supplier_id = po.supplier_id "
        "AND sp.product_id = i.product_id "
        "WHERE sp.id IS NULL OR sp.unit_cost != i.unit_cost "
        "OR i.quantity < sp.min_order_qty",
    )
    assert wrong == [(0,)]


def test_receipt_movements_match_received_quantities(simulated: Simulated) -> None:
    _, engine, _ = simulated
    received = dict(
        rows(
            engine,
            "SELECT po.po_number, SUM(i.quantity_received) FROM purchase_orders po "
            "JOIN purchase_order_items i ON i.purchase_order_id = po.id GROUP BY po.id",
        )
    )
    moved: dict[str, int] = defaultdict(int)
    for reason, units in rows(
        engine,
        "SELECT reason, on_hand_delta FROM inventory_movements "
        "WHERE movement_type = 'receipt' AND reason LIKE 'Purchase order %'",
    ):
        moved[reason.split()[2]] += units
    assert {k: v for k, v in received.items() if v} == dict(moved)


def test_suppliers_are_late_more_often_in_peak_season(simulated: Simulated) -> None:
    _, engine, _ = simulated
    late = {True: [], False: []}
    for ordered, received, expected in rows(
        engine,
        "SELECT ordered_at, received_at, expected_date FROM purchase_orders "
        "WHERE status = 'received'",
    ):
        ordered_day = parse(ordered).date()
        arrived = next_working_day(date.fromisoformat(expected))  # due, moved off weekends
        late[is_peak_season(ordered_day)].append(parse(received).date() > arrived)
    peak = sum(late[True]) / len(late[True])
    normal = sum(late[False]) / len(late[False])
    assert 0.03 < normal < 0.3
    assert peak > normal


def test_a_small_share_of_demand_finds_empty_shelves(simulated: Simulated) -> None:
    _, _, extra = simulated
    demand = extra["demand"]
    assert 0.01 < demand.short / demand.wanted < 0.15  # the simple policy is not perfect


def test_the_application_reads_the_purchasing_history(simulated: Simulated) -> None:
    ctx, engine, _ = simulated
    end = ctx.config.end_date
    with Session(engine) as session:
        suppliers = DashboardService(session).suppliers(
            DateRange(end - timedelta(days=365), end), include_financials=True, today=end
        )
        inventory = DashboardService(session).inventory(
            DateRange(end - timedelta(days=29), end), include_financials=True
        )
    assert suppliers.received_orders > 50
    assert suppliers.lead_time_avg_days > 1
    assert 30 < suppliers.on_time.percent < 100
    assert inventory.totals.units_on_hand > 0


def test_purchasing_is_reproducible(
    tmp_path: Path, simulated: Simulated, simulator: Callable[..., Simulated]
) -> None:
    _, first, _ = simulated
    _, again, _ = simulator(tmp_path / "again.db")
    query = "SELECT * FROM purchase_orders ORDER BY id"
    assert rows(again, query) == rows(first, query)


# ------------------------------------------------------------------------ the policy
def test_reorder_policy_and_second_sources(simulated: Simulated) -> None:
    ctx, _, extra = simulated
    process: PurchasingProcess = extra["purchasing"]
    assert process.reorder_point(2.0, 10) == 36.0  # 2 a day x (10 + 8 safety days)
    assert process.order_up_to(2.0, 10) == 96.0  # + 30 days of cover
    with_second = next(p for p in ctx.products if len(p.supplier_ids) == 2)
    preferred, second = with_second.supplier_ids
    assert process.choose_supplier(with_second, available=5) == preferred
    expected = second if process.lead_days(second) < process.lead_days(preferred) else preferred
    assert process.choose_supplier(with_second, available=0) == expected


def test_working_days() -> None:
    assert is_working_day(date(2026, 11, 12))  # Thursday
    assert not is_working_day(date(2026, 11, 14))  # Saturday
    assert not is_working_day(date(2025, 12, 25))
    assert (1, 1) in PUBLIC_HOLIDAYS
    assert next_working_day(date(2026, 11, 14)) == date(2026, 11, 16)
    assert next_working_day(date(2025, 12, 24)) == date(2025, 12, 24)
    assert next_working_day(date(2025, 12, 25)) == date(2025, 12, 29)


def test_demand_tracker_moves_from_the_prior_to_history(simulated: Simulated) -> None:
    ctx, _, _ = simulated
    tracker = DemandTracker(ctx)
    product = ctx.products[0]
    prior = tracker.daily_rate(product.id, 1)
    assert prior == pytest.approx(product.profile.base_rate * 0.92)
    for day in range(TRACKING_DAYS):
        tracker.start_day(day)
        tracker.record(product.id, 1, 10, day)
    tracker.start_day(TRACKING_DAYS)  # day 28 starts: the window is full history
    assert tracker.daily_rate(product.id, 1) == pytest.approx(10 * (TRACKING_DAYS - 1) / 28)
    for day in range(TRACKING_DAYS, 2 * TRACKING_DAYS + 1):
        tracker.start_day(day)
    assert tracker.daily_rate(product.id, 1) == 0  # four quiet weeks later


# --------------------------------------------------------------------------- put-away
def test_put_away_rules(simulated: Simulated, builder: Callable) -> None:
    ctx, _, _ = simulated
    ledger = StockLedger(ctx)
    heavy = replace(ctx.products[0], id=999, weight_kg=HEAVY_KG + 2, storage="picking")
    first = ctx.bins[ledger.preferences(heavy, 1)[0] - 1]
    assert first.level == 1  # heavy goods low
    fastest = max(
        (p for p in ctx.products if p.storage == "picking"), key=lambda p: p.profile.base_rate
    )
    light = [p for p in ctx.products if p.storage == "picking" and p.weight_kg < 8]
    slowest = min(light, key=lambda p: p.profile.base_rate)
    near = ctx.bins[ledger.preferences(fastest, 1)[0] - 1]
    far = ctx.bins[ledger.preferences(slowest, 1)[0] - 1]
    assert near.distance_m < far.distance_m  # fast movers close to packing
    assert near.zone_type == far.zone_type == "picking"


def test_receiving_respects_bin_capacity(simulated: Simulated) -> None:
    ctx, _, _ = simulated
    ledger = StockLedger(ctx)
    product = max(ctx.products, key=lambda p: p.volume_cm3)
    when = at(ctx.config.start_date, 6)
    capacity = sum(ledger.room_for(product, b) for b in ledger.preferences(product, 1))
    got = ledger.receive(product.id, 1, capacity + 50, when, reason="x")
    assert got == capacity  # the rest has no room
    assert ledger.receive(product.id, 1, 1, when, reason="x") == 0
    assert (
        ledger.remove(product.id, 1, capacity + 1, when, movement_type="adjustment", reason="x")
        == capacity
    )
    assert ledger.available(product.id, 1) == 0


def test_simulation_days_cover_the_history(simulated: Simulated) -> None:
    ctx, _, extra = simulated
    sim: Simulation = extra["sim"]
    assert sim.days[0] == ctx.config.start_date
    assert sim.days[-1] == ctx.config.end_date
    assert len(sim.days) == 730


# ------------------------------------------------ single situations, set up on purpose
MONDAY = date(2026, 6, 1)


@pytest.fixture()
def fresh(
    tmp_path: Path, builder: Callable
) -> tuple[GenerationContext, Simulation, PurchasingProcess]:
    ctx, _ = builder(tmp_path / "fresh.db")
    return ctx, Simulation(ctx), PurchasingProcess(ctx)


def demand_of(sim: Simulation, product_id: int, per_day: float) -> None:
    """Make the tracker believe the product sold `per_day` units a day lately."""
    for day in range(TRACKING_DAYS):
        sim.demand.start_day(day)
        sim.demand.record(product_id, 1, per_day, day)
    sim.demand.start_day(TRACKING_DAYS)
    sim.demand.window[product_id, 1, TRACKING_DAYS % TRACKING_DAYS] = per_day


def single_product(ctx: GenerationContext, product_id: int) -> None:
    ctx.products[:] = [p for p in ctx.products if p.id == product_id]


def test_orders_exactly_at_the_reorder_point(fresh: tuple) -> None:
    ctx, sim, process = fresh
    product = next(p for p in ctx.products if p.storage == "picking")
    single_product(ctx, product.id)
    product.min_order_qty = 1
    demand_of(sim, product.id, 2.0)
    lead = process.lead_days(product.supplier_ids[0])
    point = int(process.reorder_point(2.0, lead))

    sim.ledger.receive(product.id, 1, point + 1, at(MONDAY, 6), reason="x")
    process._review(sim, MONDAY)
    assert process.orders == []  # above the reorder point: nothing to do

    sim.ledger.remove(product.id, 1, 1, at(MONDAY, 7), movement_type="adjustment", reason="x")
    process._review(sim, MONDAY)
    (order,) = process.orders
    assert order.lines[0].quantity == int(process.order_up_to(2.0, lead)) - point
    process._review(sim, MONDAY)
    assert len(process.orders) == 1  # what is on order counts: no second order


def test_minimum_order_quantity(fresh: tuple) -> None:
    ctx, sim, process = fresh
    product = next(p for p in ctx.products if p.storage == "picking")
    single_product(ctx, product.id)
    demand_of(sim, product.id, 0.1)
    product.min_order_qty = 500
    process._review(sim, MONDAY)
    assert process.orders[0].lines[0].quantity == 500


def test_deliveries_without_room_wait_for_the_next_working_day(fresh: tuple) -> None:
    ctx, sim, process = fresh
    product = max((p for p in ctx.products if p.storage == "picking"), key=lambda p: p.volume_cm3)
    single_product(ctx, product.id)
    product.min_order_qty = 1
    demand_of(sim, product.id, 1.0)
    room = sum(sim.ledger.room_for(product, b) for b in sim.ledger.preferences(product, 1))
    process._place(
        product.supplier_ids[0], 1, [OrderLine(product.id, room + 7, Decimal(1))], MONDAY
    )
    order = process.orders[0]
    process.on_order[(product.id, 1)] = room + 7
    process.deliveries = {MONDAY: [(order, order.lines[0], room + 7)]}

    process._receive(sim, MONDAY)
    assert order.lines[0].received == room
    assert order.received_on is None  # not complete yet
    assert process.on_order[(product.id, 1)] == 7
    tuesday = MONDAY + timedelta(days=1)
    assert process.deliveries[tuesday][0][2] == 7

    sim.ledger.remove(product.id, 1, 10, at(MONDAY, 15), movement_type="adjustment", reason="x")
    process._receive(sim, tuesday)
    assert order.complete
    assert order.received_on == tuesday


def test_status_of_open_orders(fresh: tuple) -> None:
    ctx, sim, process = fresh
    product = ctx.products[0]
    lines = [OrderLine(product.id, 10, Decimal(1)), OrderLine(ctx.products[1].id, 5, Decimal(1))]
    process._place(product.supplier_ids[0], 1, lines, MONDAY)
    statuses = lambda: [r["status"] for r in process._order_rows()]  # noqa: E731
    assert statuses() == ["ordered"]
    lines[0].received = 4
    assert statuses() == ["partially_received"]
    lines[0].received, lines[1].received = 10, 5
    assert statuses() == ["received"]


def test_heavy_goods_fill_the_lowest_shelves_first(simulated: Simulated) -> None:
    ctx, _, _ = simulated
    ledger = StockLedger(ctx)
    heavy = replace(ctx.products[0], id=999, weight_kg=Decimal("10"), storage="picking")
    bins = {b.id: b for b in ctx.bins}
    order = ledger.preferences(heavy, 1)
    zone = bins[order[0]].zone_type
    levels = [bins[b].level for b in order if bins[b].zone_type == zone]
    assert levels == sorted(levels)


def test_demand_tracker_blends_prior_and_history(simulated: Simulated) -> None:
    ctx, _, _ = simulated
    tracker = DemandTracker(ctx)
    product = ctx.products[0]
    prior = tracker.daily_rate(product.id, 1)
    for day in range(14):
        tracker.start_day(day)
        tracker.record(product.id, 1, 20, day)
    tracker.start_day(14)  # half of the window is history (20 a day)
    assert tracker.daily_rate(product.id, 1) == pytest.approx(0.5 * 20 + 0.5 * prior)
