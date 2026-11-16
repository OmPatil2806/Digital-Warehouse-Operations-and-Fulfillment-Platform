"""Picking, packing, shipping, delays and returns."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from math import ceil
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.dashboard_service import DashboardService, DateRange
from app.services.fulfillment_service import FulfillmentService
from data_generation.context import GenerationContext
from data_generation.generate_fulfillment import FulfillmentProcess
from data_generation.generate_orders import OrderBook, OrdersProcess, SimLine
from data_generation.generate_shipments import ShipmentsProcess, add_working_days
from data_generation.simulation import Simulation, at

Simulated = tuple[GenerationContext, Engine, dict]


def rows(engine: Engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(r) for r in connection.execute(text(sql))]


def parse(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# -------------------------------------------------------------------------- picking
def test_picked_units_match_the_tasks_and_the_stock(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    mismatches = rows(
        engine,
        "SELECT i.id FROM order_items i LEFT JOIN ("
        "  SELECT order_item_id, SUM(quantity_picked) AS picked FROM picking_tasks "
        "  GROUP BY order_item_id) t ON t.order_item_id = i.id "
        "WHERE COALESCE(t.picked, 0) != i.quantity_picked",
    )
    assert mismatches == []
    moved = rows(
        engine,
        "SELECT -SUM(on_hand_delta) FROM inventory_movements WHERE movement_type = 'pick'",
    )
    picked = rows(engine, "SELECT SUM(quantity_picked) FROM order_items")
    assert moved == picked
    wrong = rows(
        engine,
        "SELECT COUNT(*) FROM picking_tasks t JOIN stock_reservations r ON r.id = t.reservation_id "
        "WHERE r.quantity != t.quantity OR r.bin_id != t.bin_id "
        "OR (t.status IN ('completed', 'short') AND r.status = 'active')",
    )
    assert wrong == [(0,)]


def test_the_route_starts_at_the_farthest_rack(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    routes = defaultdict(list)
    for order_id, sequence, distance, created in rows(
        engine,
        "SELECT t.order_id, t.sequence, r.distance_to_packing_m, t.created_at FROM picking_tasks t "
        "JOIN bins b ON b.id = t.bin_id JOIN shelves s ON s.id = b.shelf_id "
        "JOIN racks r ON r.id = s.rack_id ORDER BY t.order_id, t.sequence",
    ):
        routes[(order_id, created)].append((sequence, distance))
    for steps in routes.values():  # tasks created together form one route
        distances = [d for _, d in steps]
        assert distances == sorted(distances, reverse=True)
    for order_id in {o for o, _ in routes}:
        sequences = sorted(s for (o, _), steps in routes.items() if o == order_id for s, _ in steps)
        assert sequences == list(range(1, len(sequences) + 1))


def test_short_picks_are_corrected_and_counted(with_orders: Simulated) -> None:
    _, engine, extra = with_orders
    shorts = rows(
        engine,
        "SELECT t.order_id, t.bin_id, t.quantity - t.quantity_picked, t.short_reason, "
        "o.order_number FROM picking_tasks t JOIN orders o ON o.id = t.order_id "
        "WHERE t.status = 'short'",
    )
    assert len(shorts) == extra["fulfillment"].short_picks > 0
    adjustments = rows(engine, "SELECT bin_id, kind, reason FROM stock_adjustments")
    counts = {r[0] for r in rows(engine, "SELECT bin_id FROM cycle_counts")}
    for _order_id, bin_id, missing, reason, number in shorts:
        assert missing > 0 and reason
        assert any(b == bin_id and number in r for b, _k, r in adjustments)
        assert bin_id in counts
    assert {k for _, k, _ in adjustments} == {"decrease", "damage", "write_off"}
    open_counts = rows(engine, "SELECT COUNT(*) FROM cycle_counts WHERE status != 'completed'")
    assert open_counts[0][0] <= 2  # only the last days' counts are still open
    differences = rows(
        engine,
        "SELECT COUNT(*) FROM cycle_count_lines l JOIN cycle_counts c ON c.id = l.cycle_count_id "
        "WHERE c.status = 'completed' AND l.counted_quantity != l.expected_quantity",
    )
    assert differences == [(0,)]


def test_no_picking_at_the_weekend_or_before_the_order_was_ready(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    for (started,) in rows(engine, "SELECT started_at FROM picking_tasks"):
        assert parse(started).weekday() < 5
    early = rows(
        engine,
        "SELECT COUNT(*) FROM picking_tasks t JOIN orders o ON o.id = t.order_id "
        "WHERE t.started_at < o.confirmed_at",
    )
    assert early == [(0,)]


# -------------------------------------------------------------------------- packing
def test_packing_records_parcels_and_weight(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    weights = {p.id: p.weight_kg for p in ctx.products}
    picked = defaultdict(Decimal)
    for order_id, product_id, units in rows(
        engine, "SELECT order_id, product_id, quantity_picked FROM order_items"
    ):
        picked[order_id] += weights[product_id] * units
    tasks = rows(engine, "SELECT order_id, status, package_count, weight_kg FROM packing_tasks")
    assert tasks
    for order_id, status, parcels, weight in tasks:
        assert status == "completed" and parcels >= 1
        expected = picked[order_id] + Decimal("0.25") * parcels
        assert Decimal(weight) / 1000 == expected  # grams in the database
    unpacked = rows(
        engine,
        "SELECT COUNT(*) FROM order_items WHERE quantity_packed != quantity_picked "
        "AND order_id IN (SELECT order_id FROM packing_tasks)",
    )
    assert unpacked == [(0,)]


# ------------------------------------------------------------------------ shipments
def test_shipments_and_their_tracking(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    transit = {c.id: c.transit_days for c in ctx.carriers}
    shipments = rows(
        engine,
        "SELECT s.id, s.carrier_id, s.shipped_at, s.expected_delivery_date, s.delivered_at, "
        "s.status, o.status, o.delivered_at FROM shipments s JOIN orders o ON o.id = s.order_id",
    )
    events = defaultdict(list)
    for shipment_id, kind, when in rows(
        engine,
        "SELECT shipment_id, event_type, occurred_at FROM shipment_events ORDER BY occurred_at, id",
    ):
        events[shipment_id].append((kind, parse(when)))
    for (
        sid,
        carrier,
        shipped,
        expected,
        delivered,
        status,
        order_status,
        order_delivered,
    ) in shipments:
        ship_day = parse(shipped).date()
        assert date.fromisoformat(expected) == add_working_days(ship_day, transit[carrier])
        kinds = [k for k, _ in events[sid]]
        assert kinds[0] == "dispatched"
        if delivered:
            assert status == "delivered" and kinds[-1] == "delivered"
            assert delivered == order_delivered
            late = parse(delivered).date() > date.fromisoformat(expected)
            assert ("delayed" in kinds) == late
            assert order_status in ("delivered", "returned")
        else:
            assert status in ("dispatched", "in_transit", "delayed")


def test_delayed_orders_pass_through_delayed(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    delayed_events = {
        r[0]
        for r in rows(
            engine,
            "SELECT s.order_id FROM shipment_events e JOIN shipments s ON s.id = e.shipment_id "
            "WHERE e.event_type = 'delayed'",
        )
    }
    delayed_status = {
        r[0]
        for r in rows(
            engine, "SELECT order_id FROM order_status_history WHERE to_status = 'delayed'"
        )
    }
    assert delayed_events == delayed_status != set()


def test_orders_after_the_cut_off_ship_a_working_day_later(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    for created, shipped in rows(
        engine, "SELECT created_at, shipped_at FROM orders WHERE shipped_at IS NOT NULL"
    ):
        created_at, shipped_at = parse(created), parse(shipped)
        assert shipped_at.weekday() < 5
        if created_at.hour >= 14:
            assert shipped_at.date() > created_at.date()


# ------------------------------------------------------------------- the delay model
def late_shares(engine: Engine, group_sql: str) -> dict:
    return {
        key: share
        for key, share in rows(
            engine,
            f"SELECT {group_sql} AS k, AVG(DATE(s.delivered_at) > s.expected_delivery_date) "
            "FROM shipments s JOIN orders o ON o.id = s.order_id "
            "JOIN (SELECT order_id, SUM(quantity_shipped) AS units FROM order_items "
            "GROUP BY order_id) i ON i.order_id = o.id "
            "JOIN carriers c ON c.id = s.carrier_id "
            "WHERE s.delivered_at IS NOT NULL GROUP BY k",
        )
    }


def test_delays_follow_the_risk_factors(busy_pipeline: Simulated) -> None:
    ctx, engine, _ = busy_pipeline
    waited = late_shares(
        engine,
        "o.id IN (SELECT order_id FROM order_status_history "
        "WHERE to_status IN ('backordered', 'partially_allocated'))",
    )
    assert waited[1] > 1.8 * waited[0]
    size = late_shares(engine, "i.units > 10")
    assert size[1] > 1.5 * size[0]
    month = late_shares(engine, "CAST(strftime('%m', s.shipped_at) AS INTEGER)")
    normal = sum(month[m] for m in range(1, 11)) / 10
    assert month[12] > 1.6 * normal
    assert 0.04 < normal < 0.15
    by_carrier = late_shares(engine, "c.code")
    reliability = {c.code: c.reliability for c in ctx.carriers}
    ranked = sorted(by_carrier, key=lambda code: reliability[code])  # least reliable first
    assert by_carrier[ranked[0]] > by_carrier[ranked[-1]]


def test_december_backlog_slows_fulfillment(busy_pipeline: Simulated) -> None:
    _, engine, _ = busy_pipeline
    hours = dict(
        rows(
            engine,
            "SELECT CAST(strftime('%m', created_at) AS INTEGER), "
            "AVG((julianday(shipped_at) - julianday(confirmed_at)) * 24) FROM orders "
            "WHERE shipped_at IS NOT NULL GROUP BY 1",
        )
    )
    assert hours[12] > 1.5 * hours[6]
    assert 12 < hours[6] < 72  # a day or two in normal times


# --------------------------------------------------------------------------- returns
def test_returns_come_back_into_stock(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    items = rows(
        engine,
        "SELECT r.id, r.status, ri.quantity, ri.condition, ri.bin_id, oi.quantity_shipped "
        "FROM returns r JOIN return_items ri ON ri.return_id = r.id "
        "JOIN order_items oi ON oi.id = ri.order_item_id",
    )
    assert items
    movements = defaultdict(lambda: [0, 0])
    for reference, units, damaged in rows(
        engine,
        "SELECT reference_id, on_hand_delta, damaged_delta FROM inventory_movements "
        "WHERE movement_type = 'return'",
    ):
        movements[reference][0] += units
        movements[reference][1] += damaged
    expected = defaultdict(lambda: [0, 0])
    for return_id, status, quantity, condition, bin_id, shipped in items:
        assert quantity <= shipped
        if status == "completed":
            assert condition in ("restock", "damaged") and bin_id
            expected[return_id][0] += quantity
            expected[return_id][1] += quantity if condition == "damaged" else 0
        else:
            assert condition is None and bin_id is None
    assert dict(movements) == dict(expected)
    returned = rows(
        engine,
        "SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id "
        "WHERE o.status = 'returned' GROUP BY o.id HAVING SUM(i.quantity_returned) = 0",
    )
    assert returned == []


def test_returns_go_to_the_returns_zone(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    zones = rows(
        engine,
        "SELECT z.zone_type, COUNT(*) FROM return_items ri JOIN bins b ON b.id = ri.bin_id "
        "JOIN shelves s ON s.id = b.shelf_id JOIN racks r ON r.id = s.rack_id "
        "JOIN zones z ON z.id = r.zone_id GROUP BY 1",
    )
    assert dict(zones).get("returns", 0) >= 0.9 * sum(n for _, n in zones)


def test_return_rates_follow_the_categories(busy_pipeline: Simulated) -> None:
    _, engine, _ = busy_pipeline
    rates = dict(
        rows(
            engine,
            "SELECT c.name, SUM(COALESCE(ri.quantity, 0)) * 1.0 / SUM(oi.quantity_shipped) "
            "FROM order_items oi JOIN products p ON p.id = oi.product_id "
            "JOIN categories c ON c.id = p.category_id "
            "LEFT JOIN return_items ri ON ri.order_item_id = oi.id GROUP BY 1",
        )
    )
    assert rates["Electronics"] > 3 * rates["Office Supplies"] > rates["Food & Beverages"]


# ------------------------------------------------------------------- the application
def test_the_application_continues_fulfillment(tmp_path: Path, order_simulator: Callable) -> None:
    """The application's own fulfillment works on the generated data (own copy)."""
    ctx, engine, _ = order_simulator(tmp_path / "app.db")
    end = ctx.config.end_date
    with Session(engine) as session:
        dashboard = DashboardService(session).fulfillment(DateRange(end - timedelta(days=364), end))
        assert dashboard.on_time_delivery.total > 100
        assert 80 < dashboard.on_time_delivery.percent < 97
        assert dashboard.picking_accuracy.percent > 99
        ready = session.scalar(
            text("SELECT id FROM orders WHERE status = 'inventory_reserved' LIMIT 1")
        )
        if ready is not None:
            tasks = FulfillmentService(session).allocate(ready, user=None)
            assert tasks


# ----------------------------------------------------------------------- housekeeping
def test_weekly_housekeeping(with_orders: Simulated) -> None:
    ctx, engine, extra = with_orders
    housekeeping = extra["housekeeping"]
    assert housekeeping.written_off > 0 and housekeeping.moved > 0
    for created, reason in rows(
        engine, "SELECT created_at, reason FROM stock_adjustments WHERE kind = 'write_off'"
    ):
        assert parse(created).weekday() == 4  # Fridays
        assert reason == "Weekly disposal of damaged goods"
    # Transfers take returned goods out of the returns zone into normal storage.
    zone_of = dict(
        rows(
            engine,
            "SELECT b.id, z.zone_type FROM bins b JOIN shelves s ON s.id = b.shelf_id "
            "JOIN racks r ON r.id = s.rack_id JOIN zones z ON z.id = r.zone_id",
        )
    )
    transfers = rows(engine, "SELECT from_bin_id, to_bin_id, quantity FROM stock_transfers")
    assert transfers
    for from_bin, to_bin, _ in transfers:
        assert zone_of[from_bin] == "returns" != zone_of[to_bin]
    moved = rows(
        engine,
        "SELECT movement_type, SUM(ABS(on_hand_delta)) FROM inventory_movements "
        "WHERE movement_type LIKE 'transfer_%' GROUP BY 1",
    )
    total = sum(q for _, _, q in transfers)
    assert dict(moved) == {"transfer_in": total, "transfer_out": total}


def test_damaged_and_returned_goods_do_not_pile_up(with_orders: Simulated) -> None:
    """Only what arrived after the last housekeeping round can still be there."""
    ctx, engine, _ = with_orders
    end = ctx.config.end_date
    last_friday = end - timedelta(days=(end.weekday() - 4) % 7)
    since = datetime(last_friday.year, last_friday.month, last_friday.day, 15, tzinfo=UTC)
    (damaged,) = rows(engine, "SELECT COALESCE(SUM(quantity_damaged), 0) FROM inventory")[0]
    (recent,) = rows(
        engine,
        "SELECT COALESCE(SUM(damaged_delta), 0) FROM inventory_movements "
        f"WHERE damaged_delta > 0 AND created_at >= '{since:%Y-%m-%d %H:%M:%S}'",
    )[0]
    assert damaged <= recent


# ------------------------------------------------ single rules, set up on purpose
def test_parcels_follow_weight_and_volume(with_orders: Simulated) -> None:
    ctx, engine, _ = with_orders
    products = {p.id: p for p in ctx.products}
    net = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for order_id, product_id, units in rows(
        engine, "SELECT order_id, product_id, quantity_picked FROM order_items"
    ):
        net[order_id][0] += products[product_id].weight_kg * units
        net[order_id][1] += products[product_id].volume_cm3 * units
    multi = 0
    for order_id, parcels in rows(engine, "SELECT order_id, package_count FROM packing_tasks"):
        weight, volume = net[order_id]
        assert parcels == max(1, ceil(weight / 20), ceil(volume / 60_000))
        multi += parcels > 1
    assert multi > 0


def test_carrier_pick_up_at_half_past_five(with_orders: Simulated) -> None:
    _, engine, _ = with_orders
    for packed, shipped in rows(
        engine,
        "SELECT p.completed_at, s.shipped_at FROM packing_tasks p "
        "JOIN shipments s ON s.order_id = p.order_id",
    ):
        packed_at, shipped_at = parse(packed), parse(shipped)
        assert 17.5 <= shipped_at.hour + shipped_at.minute / 60 <= 17.95
        assert shipped_at >= packed_at


def test_parcels_packed_after_five_leave_the_next_working_day(
    tmp_path: Path, builder: Callable
) -> None:
    ctx, _ = builder(tmp_path / "late.db")
    sim = Simulation(ctx)
    book = OrderBook(ctx)
    shipping = ShipmentsProcess(ctx, book)
    product = ctx.products[0]
    friday = date(2026, 6, 5)
    shipped = []
    for hour in (16.9, 17.1):
        order = book.new_order(
            ctx.customers[0],
            [SimLine(1, product.id, 1, Decimal(1))],
            at(friday, 8),
            priority="normal",
            requested=None,
        )
        order.warehouse_id = 1
        order.status = "packed"
        shipping.ship(sim, order, at(friday, hour), parcels=1, weight_kg=Decimal(1))
        shipped.append(order.shipment["shipped_at"].date())
    assert shipped == [friday, friday + timedelta(days=3)]  # after five: Monday


def test_picking_capacity_limits_a_day(tmp_path: Path, builder: Callable) -> None:
    ctx, _ = builder(tmp_path / "capacity.db")
    sim = Simulation(ctx)
    book = OrderBook(ctx)
    orders = OrdersProcess(ctx, book)
    shipping = ShipmentsProcess(ctx, book)
    fulfillment = FulfillmentProcess(ctx, book, shipping)
    orders.on_start(sim)
    fulfillment.on_start(sim)
    fulfillment.capacity[1] = 5  # lines per day
    product = next(p for p in ctx.products if p.storage == "picking")
    monday = date(2026, 6, 1)
    sim.ledger.receive(product.id, 1, 50, at(monday, 6), reason="x")
    placed = []
    for _ in range(4):  # 4 one-line orders, reserved before the cut-off
        order = book.new_order(
            ctx.customers[0],
            [SimLine(1, product.id, 1, Decimal(1))],
            at(monday, 8),
            priority="normal",
            requested=None,
        )
        book.transition(order, "confirmed", at(monday, 8.1))
        orders.reserve(sim, order, at(monday, 8.1))
        placed.append(order)
    fulfillment.capacity[1] = 2.5
    fulfillment.on_day(sim, monday, 0)
    assert [o.status != "inventory_reserved" for o in placed] == [True, True, True, False]
    fulfillment.on_day(sim, monday + timedelta(days=1), 1)
    assert placed[3].status != "inventory_reserved"  # done the next working day


def test_returns_use_storage_bins_when_the_returns_zone_is_full(
    tmp_path: Path, builder: Callable
) -> None:
    ctx, _ = builder(tmp_path / "full_returns.db")
    sim = Simulation(ctx)
    shipping = ShipmentsProcess(ctx, OrderBook(ctx))
    product = next(p for p in ctx.products if p.storage == "picking")
    returns = [b for b in ctx.bins if b.zone_type == "returns"]
    first = shipping._return_bin(sim, 1, product.id, 1, [])
    assert first == returns[0].id  # normally the first returns bin
    taken = [b.id for b in returns]
    fallback = shipping._return_bin(sim, 1, product.id, 1, taken)
    assert fallback is not None and sim.ledger.bins[fallback].zone_type != "returns"
    everything = [b.id for b in ctx.bins]
    assert shipping._return_bin(sim, 1, product.id, 1, everything) is None  # waits at the dock


def test_damaged_on_arrival_returns_are_mostly_damaged(busy_pipeline: Simulated) -> None:
    _, engine, _ = busy_pipeline
    shares = dict(
        rows(
            engine,
            "SELECT r.reason = 'Damaged on arrival', AVG(ri.condition = 'damaged') "
            "FROM returns r JOIN return_items ri ON ri.return_id = r.id "
            "WHERE r.status = 'completed' GROUP BY 1",
        )
    )
    assert shares[1] > 0.6
    assert 0.1 < shares[0] < 0.4
