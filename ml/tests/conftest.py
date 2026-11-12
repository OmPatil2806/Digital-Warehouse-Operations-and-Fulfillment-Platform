"""Shared fixtures: a small generated database (master data and layout only so far)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from data_generation.config import get_config
from data_generation.context import GenerationContext
from data_generation.database import BatchWriter, prepare_database
from data_generation.generate_master_data import generate_master_data
from data_generation.generate_purchasing import PurchasingProcess
from data_generation.generate_warehouse_layout import generate_warehouse_layout
from data_generation.patterns import demand_rate, sample_units
from data_generation.simulation import Simulation, at

END = date(2026, 11, 10)


def build(path: Path, size: str = "small", **overrides: int) -> tuple[GenerationContext, Engine]:
    config = get_config(size, end_date=END, **overrides)
    engine = prepare_database(path)
    ctx = GenerationContext(config=config, writer=BatchWriter(engine, config.batch_size))
    generate_master_data(ctx)
    generate_warehouse_layout(ctx)
    return ctx, engine


@pytest.fixture()
def builder() -> Callable[..., tuple[GenerationContext, Engine]]:
    """`build` for tests that need their own database (imports from conftest would clash
    with the backend's `tests` package)."""
    return build


@pytest.fixture(scope="session")
def small(tmp_path_factory: pytest.TempPathFactory) -> tuple[GenerationContext, Engine]:
    return build(tmp_path_factory.mktemp("small") / "small.db")


class FakeDemand:
    """Stand-in for customer orders until Step 4: take the sampled demand out of stock."""

    def __init__(self, ctx: GenerationContext) -> None:
        self.ctx = ctx
        self.rng = ctx.rng("orders")
        self.wanted = 0
        self.short = 0

    def on_start(self, sim: Simulation) -> None:
        pass

    def on_finish(self, sim: Simulation) -> None:
        pass

    def on_day(self, sim: Simulation, day: date, day_index: int) -> None:
        for product in self.ctx.products:
            rate = demand_rate(product.profile, day, day_index, self.ctx.config.days)
            units = sample_units(self.rng, product.profile, rate)
            for warehouse_id in self.ctx.warehouse_ids:
                if not units:
                    continue
                sim.demand.record(product.id, warehouse_id, units, day_index)
                taken = sim.ledger.remove(
                    product.id,
                    warehouse_id,
                    units,
                    at(day, 14),
                    movement_type="adjustment",
                    reason="Test demand",
                )
                self.wanted += units
                self.short += units - taken


def simulate(path: Path, **overrides: int) -> tuple[GenerationContext, Engine, dict]:
    ctx, engine = build(path, **overrides)
    sim = Simulation(ctx)
    purchasing = PurchasingProcess(ctx)
    demand = FakeDemand(ctx)
    sim.run([purchasing, demand])
    return ctx, engine, {"sim": sim, "purchasing": purchasing, "demand": demand}


@pytest.fixture(scope="session")
def simulated(tmp_path_factory: pytest.TempPathFactory) -> tuple[GenerationContext, Engine, dict]:
    """Small dataset run through two years of purchasing against stand-in demand."""
    return simulate(tmp_path_factory.mktemp("sim") / "sim.db")


@pytest.fixture()
def simulator() -> Callable[..., tuple[GenerationContext, Engine, dict]]:
    return simulate
