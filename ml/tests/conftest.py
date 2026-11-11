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
from data_generation.generate_warehouse_layout import generate_warehouse_layout

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
