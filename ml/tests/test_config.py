from datetime import date

import pytest

from data_generation.config import DEFAULT_SEED, SIZE_NAMES, get_config


def test_full_size_matches_the_project_document() -> None:
    full = get_config("full", end_date=date(2026, 11, 10))
    assert (full.warehouses, full.zones, full.racks) == (3, 18, 180)
    assert full.bins == 4_320  # "several thousand"
    assert (full.products, full.suppliers, full.customers) == (2_000, 100, 10_000)
    assert full.orders == 500_000
    assert full.days == 730  # two years
    assert full.start_date == date(2024, 11, 11)
    assert round(full.orders_per_day) == 685


def test_sizes_grow_and_small_is_quick() -> None:
    sizes = [get_config(name) for name in SIZE_NAMES]
    assert [s.name for s in sizes] == ["small", "medium", "full"]
    for smaller, larger in zip(sizes, sizes[1:], strict=False):
        assert smaller.products < larger.products
        assert smaller.orders < larger.orders
        assert smaller.bins < larger.bins
    small = sizes[0]
    assert (small.products, small.orders, small.bins) == (50, 500, 300)


def test_seed_end_date_and_overrides() -> None:
    config = get_config("small", seed=7, end_date=date(2026, 1, 31), orders=1_000)
    assert config.seed == 7
    assert config.orders == 1_000
    assert config.end_date == date(2026, 1, 31)
    assert config.start_date == date(2024, 2, 2)
    assert get_config().seed == DEFAULT_SEED


@pytest.mark.parametrize(
    ("overrides", "message"),
    [({"orders": 0}, "orders must be at least 1"), ({"products": 5}, "at least 8 products")],
)
def test_invalid_values_are_refused(overrides: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        get_config("small", **overrides)


def test_unknown_size() -> None:
    with pytest.raises(ValueError, match="choose one of: small, medium, full"):
        get_config("huge")
