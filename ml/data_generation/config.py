"""Dataset sizes and the random seed (project document, section 11.1).

Three sizes share one code path:

- ``small``  for development and CI (seconds),
- ``medium`` for realistic dashboards on a PC (minutes),
- ``full``   the target volume of the project document, for analytics and ML training.

Every run with the same size, seed and end date produces exactly the same data.
"""

from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime, timedelta

DEFAULT_SEED = 20261111
HISTORY_DAYS = 730  # two years


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    seed: int
    end_date: date  # last simulated day (included)
    days: int
    # Warehouse layout: warehouses x zones x racks x shelves x bins
    warehouses: int
    zones_per_warehouse: int
    racks_per_zone: int
    shelves_per_rack: int
    bins_per_shelf: int
    # Master data
    products: int
    suppliers: int
    customers: int
    carriers: int
    # Activity over the whole history
    orders: int
    batch_size: int  # rows per database insert batch

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, int) and field.name != "seed" and value < 1:
                raise ValueError(f"{field.name} must be at least 1, got {value}")
        if self.products < 8:
            raise ValueError("at least 8 products are needed (one per category)")

    @property
    def start_date(self) -> date:
        return self.end_date - timedelta(days=self.days - 1)

    @property
    def zones(self) -> int:
        return self.warehouses * self.zones_per_warehouse

    @property
    def racks(self) -> int:
        return self.zones * self.racks_per_zone

    @property
    def bins(self) -> int:
        return self.racks * self.shelves_per_rack * self.bins_per_shelf

    @property
    def orders_per_day(self) -> float:
        return self.orders / self.days


def _today() -> date:
    return datetime.now(UTC).date()


_SIZES: dict[str, dict[str, int]] = {
    "small": {
        "warehouses": 1,
        "zones_per_warehouse": 4,
        "racks_per_zone": 5,
        "shelves_per_rack": 3,
        "bins_per_shelf": 5,  # 300 bins
        "products": 50,
        "suppliers": 10,
        "customers": 200,
        "carriers": 4,
        "orders": 500,
        "batch_size": 1_000,
    },
    "medium": {
        "warehouses": 1,
        "zones_per_warehouse": 6,
        "racks_per_zone": 10,
        "shelves_per_rack": 4,
        "bins_per_shelf": 6,  # 1,440 bins
        "products": 500,
        "suppliers": 30,
        "customers": 2_000,
        "carriers": 4,
        "orders": 50_000,
        "batch_size": 5_000,
    },
    "full": {  # the target volume of the project document
        "warehouses": 3,
        "zones_per_warehouse": 6,  # 18 zones
        "racks_per_zone": 10,  # 180 racks
        "shelves_per_rack": 4,
        "bins_per_shelf": 6,  # 4,320 bins
        "products": 2_000,
        "suppliers": 100,
        "customers": 10_000,
        "carriers": 6,
        "orders": 500_000,
        "batch_size": 10_000,
    },
}

SIZE_NAMES = tuple(_SIZES)


def get_config(
    size: str = "small",
    *,
    seed: int = DEFAULT_SEED,
    end_date: date | None = None,
    **overrides: int,
) -> DatasetConfig:
    """The configuration for a size; any field can be overridden (e.g. orders=1000)."""
    if size not in _SIZES:
        raise ValueError(f"Unknown size {size!r}; choose one of: {', '.join(SIZE_NAMES)}")
    config = DatasetConfig(
        name=size,
        seed=seed,
        end_date=end_date or _today(),
        days=HISTORY_DAYS,
        **_SIZES[size],
    )
    return replace(config, **overrides) if overrides else config
