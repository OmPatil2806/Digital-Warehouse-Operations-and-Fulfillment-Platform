"""The day-by-day simulation: the warehouse's two-year history, one day at a time.

Each stage (purchasing now; orders, fulfillment and shipments in the next steps) is a
*process* with three hooks. Every simulated day the engine calls the processes in a
fixed order, so goods received in the morning can be picked for orders the same day::

    for day in history:
        purchasing.on_day   (deliveries arrive, stock is reviewed and reordered)
        orders.on_day       (Step 4)
        fulfillment.on_day  (Step 5)

The stock lives in one shared ``StockLedger``; what customers ordered per product and
warehouse is remembered by the ``DemandTracker`` (the purchasing policy uses it).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

import numpy as np

from data_generation.context import GenerationContext
from data_generation.stock import StockLedger

# Share of all demand served by each warehouse (Stuttgart, Hamburg, Leipzig).
WAREHOUSE_SHARES = (0.5, 0.3, 0.2)
TRACKING_DAYS = 28  # the purchasing policy looks at the last four weeks


def warehouse_shares(count: int) -> list[float]:
    shares = WAREHOUSE_SHARES[:count]
    total = sum(shares)
    return [share / total for share in shares]


def at(day: date, hour: float) -> datetime:
    """A moment on a simulated day (UTC)."""
    return datetime.combine(day, time.min, tzinfo=UTC) + timedelta(hours=hour)


class DemandTracker:
    """Units ordered per product and warehouse over the last `TRACKING_DAYS` days.

    Before any history exists the expected demand of the product's profile is used,
    so purchasing can plan from day one.
    """

    def __init__(self, ctx: GenerationContext) -> None:
        shares = warehouse_shares(len(ctx.warehouse_ids))
        self.window = np.zeros((len(ctx.products) + 1, len(shares) + 1, TRACKING_DAYS))
        self.days_seen = 0
        self.prior = np.zeros((len(ctx.products) + 1, len(shares) + 1))
        for product in ctx.products:
            for index, share in enumerate(shares, start=1):
                self.prior[product.id, index] = product.profile.base_rate * 0.92 * share

    def record(self, product_id: int, warehouse_id: int, units: int, day_index: int) -> None:
        self.window[product_id, warehouse_id, day_index % TRACKING_DAYS] += units

    def start_day(self, day_index: int) -> None:
        """Forget the day that falls out of the window."""
        self.window[:, :, day_index % TRACKING_DAYS] = 0
        self.days_seen = min(TRACKING_DAYS, day_index)

    def daily_rate(self, product_id: int, warehouse_id: int) -> float:
        """Average units per day in the window; the prior while history is short."""
        if self.days_seen < TRACKING_DAYS:
            seen = self.window[product_id, warehouse_id].sum()
            weight = self.days_seen / TRACKING_DAYS
            history = seen / self.days_seen if self.days_seen else 0.0
            return weight * history + (1 - weight) * self.prior[product_id, warehouse_id]
        return float(self.window[product_id, warehouse_id].sum() / TRACKING_DAYS)


class Process(Protocol):
    def on_start(self, sim: "Simulation") -> None: ...
    def on_day(self, sim: "Simulation", day: date, day_index: int) -> None: ...
    def on_finish(self, sim: "Simulation") -> None: ...


class Simulation:
    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.ledger = StockLedger(ctx)
        self.demand = DemandTracker(ctx)
        self.warehouse_shares = warehouse_shares(len(ctx.warehouse_ids))

    @property
    def days(self) -> list[date]:
        start = self.ctx.config.start_date
        return [start + timedelta(days=i) for i in range(self.ctx.config.days)]

    def run(self, processes: Sequence[Process]) -> None:
        for process in processes:
            process.on_start(self)
        for day_index, day in enumerate(self.days):
            self.demand.start_day(day_index)
            for process in processes:
                process.on_day(self, day, day_index)
        for process in processes:
            process.on_finish(self)
        self.ledger.finish()
