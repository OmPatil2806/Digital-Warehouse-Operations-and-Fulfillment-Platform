"""Shared state of one generation run: settings, random streams and generated entities.

Later stages (purchasing, orders, fulfillment) need to know what earlier stages made:
the products with their demand profiles, the suppliers' true reliability, the bins with
their zone type, and so on. Those facts are kept here, next to the database rows.

Every stage gets its own random stream derived from the seed, so changing one stage
does not shift the random numbers (and therefore the data) of the others.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal

import numpy as np

from data_generation.config import DatasetConfig
from data_generation.database import BatchWriter
from data_generation.patterns import DemandProfile, SupplierProfile

STAGES = (
    "catalog",
    "suppliers",
    "customers",
    "carriers",
    "layout",
    "purchasing",
    "orders",
    "fulfillment",
    "shipments",
)


@dataclass
class ProductInfo:
    id: int
    sku: str
    category: str
    unit_price: Decimal
    unit_cost: Decimal
    weight_kg: Decimal
    volume_cm3: Decimal
    min_stock: int
    max_stock: int
    storage: str  # zone type it belongs in: picking, bulk, cold or hazardous
    profile: DemandProfile
    supplier_ids: list[int] = field(default_factory=list)  # preferred first
    offer_costs: dict[int, Decimal] = field(default_factory=dict)  # supplier -> unit cost
    min_order_qty: int = 1


@dataclass
class SupplierInfo:
    id: int
    code: str
    categories: tuple[str, ...]
    profile: SupplierProfile  # the true behaviour (the stored rating is only an estimate)


@dataclass
class CustomerInfo:
    id: int
    customer_type: str
    activity: float  # relative order frequency
    name: str = ""
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None


@dataclass
class CarrierInfo:
    id: int
    code: str
    transit_days: int
    reliability: float


@dataclass
class BinInfo:
    id: int
    warehouse_id: int
    zone_type: str
    level: int
    distance_m: float
    max_weight_kg: Decimal
    max_volume_cm3: int


@dataclass
class GenerationContext:
    config: DatasetConfig
    writer: BatchWriter
    products: list[ProductInfo] = field(default_factory=list)
    suppliers: list[SupplierInfo] = field(default_factory=list)
    customers: list[CustomerInfo] = field(default_factory=list)
    carriers: list[CarrierInfo] = field(default_factory=list)
    bins: list[BinInfo] = field(default_factory=list)
    warehouse_ids: list[int] = field(default_factory=list)
    _streams: dict[str, np.random.Generator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        seeds = np.random.SeedSequence(self.config.seed).spawn(len(STAGES))
        self._streams = {
            stage: np.random.default_rng(seed) for stage, seed in zip(STAGES, seeds, strict=True)
        }

    def rng(self, stage: str) -> np.random.Generator:
        return self._streams[stage]

    @property
    def start_time(self) -> datetime:
        """Midnight (UTC) of the first simulated day: when master data "was created"."""
        return datetime.combine(self.config.start_date, time.min, tzinfo=UTC)

    def day_index(self, day: date) -> int:
        return (day - self.config.start_date).days
