"""Business patterns of the synthetic data (project document, section 11.2).

The generated data is not random: these rules shape it, and the ML models of Phase 8
should be able to learn them back. Each rule is a small, pure function so it can be
tested on its own. Randomness always comes from a ``numpy.random.Generator`` passed in
by the caller, so a run with the same seed is reproducible.

Demand of a product on a day::

    rate = base rate x weekday x season (of its category) x holidays x trend x promotion

and the units actually ordered are drawn from a Poisson distribution around that rate
(intermittent products sell on only some days).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import cache
from math import exp

import numpy as np

# =============================================================================== demand
# Monday .. Sunday. Businesses order on weekdays; weekends are quiet.
WEEKDAY_FACTORS = (1.15, 1.10, 1.05, 1.05, 1.00, 0.65, 0.45)

# Seasonal curve per category, January .. December (1.0 = an average month).
_FLAT = (1.0,) * 12
SEASONAL_CURVES: dict[str, tuple[float, ...]] = {
    # Christmas gifts, back to school
    "Laptops": (0.80, 0.80, 0.90, 0.90, 0.90, 0.90, 1.00, 1.25, 1.20, 1.00, 1.25, 1.60),
    "Electronics": (0.80, 0.80, 0.85, 0.90, 0.90, 0.90, 0.95, 1.00, 1.00, 1.05, 1.30, 1.70),
    "Accessories": (0.90, 0.85, 0.90, 0.90, 0.90, 0.95, 1.00, 1.20, 1.15, 1.00, 1.15, 1.40),
    # Back to school and the start of the business year; little in December
    "Office Supplies": (1.25, 1.05, 1.05, 0.95, 0.90, 0.85, 0.80, 1.20, 1.30, 1.00, 0.95, 0.70),
    # Winter tyres, batteries and wipers in autumn; spring service
    "Automotive Parts": (1.10, 0.95, 1.10, 1.10, 0.90, 0.85, 0.85, 0.85, 0.95, 1.25, 1.20, 0.90),
    # DIY season
    "Tools & Hardware": (0.70, 0.75, 1.00, 1.30, 1.40, 1.30, 1.15, 1.05, 0.95, 0.85, 0.80, 0.75),
    # Gifts and cooking for the holidays
    "Home & Kitchen": (0.85, 0.80, 0.90, 0.90, 0.90, 0.85, 0.85, 0.90, 0.95, 1.05, 1.35, 1.70),
    # Festive food in December, drinks in summer
    "Food & Beverages": (0.90, 0.90, 0.95, 1.00, 1.00, 1.05, 1.10, 1.10, 1.00, 0.95, 1.00, 1.25),
}
CATEGORIES = tuple(SEASONAL_CURVES)


def weekday_factor(day: date) -> float:
    return WEEKDAY_FACTORS[day.weekday()]


def season_factor(category: str, day: date, strength: float = 1.0) -> float:
    """The category's seasonal curve; `strength` 0 flattens it, 1 applies it fully."""
    curve = SEASONAL_CURVES.get(category, _FLAT)
    return 1.0 + strength * (curve[day.month - 1] - 1.0)


@cache
def black_friday(year: int) -> date:
    """The day after the fourth Thursday of November."""
    first = date(year, 11, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(days=22)


def holiday_factor(day: date) -> float:
    """Shopping peaks and closed days (German calendar)."""
    if (day.month, day.day) in {(1, 1), (12, 25), (12, 26)}:
        return 0.15  # public holidays: almost nothing is ordered
    if day.month == 12 and day.day in (24, 31):
        return 0.4
    friday = black_friday(day.year)
    if friday <= day <= friday + timedelta(days=3):  # Black Friday to Cyber Monday
        return 2.2
    if friday - timedelta(days=4) <= day < friday:  # the run-up week
        return 1.3
    if day.month == 12 and 1 <= day.day <= 20:  # Christmas shopping
        return 1.2
    return 1.0


def trend_factor(day_index: int, days: int, yearly_growth: float) -> float:
    """Steady growth (or decline) over the history; 1.0 in the middle of it."""
    years = (day_index - (days - 1) / 2) / 365
    return max(0.1, 1.0 + yearly_growth * years)


@dataclass(frozen=True)
class Promotion:
    start: date
    end: date  # included
    uplift: float  # demand multiplier while it runs

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class DemandProfile:
    """How one product sells."""

    category: str
    base_rate: float  # average units per day before the factors
    yearly_growth: float  # trend, e.g. 0.15 = +15 % per year
    season_strength: float  # 0..1.2, how strongly it follows its category's curve
    intermittent: bool  # sells only on some days (spare parts, special items)
    promotions: tuple[Promotion, ...] = field(default_factory=tuple)

    def promotion_factor(self, day: date) -> float:
        for promotion in self.promotions:
            if promotion.covers(day):
                return promotion.uplift
        return 1.0


INTERMITTENT_SHARE = 0.2  # share of products that sell only now and then
INTERMITTENT_SALE_DAY_PROBABILITY = 0.15  # on how many days they sell at all


def make_demand_profiles(
    rng: np.random.Generator,
    categories: Sequence[str],
    start: date,
    days: int,
) -> list[DemandProfile]:
    """One profile per product (the category of each product is given).

    Base rates follow a heavy-tailed (log-normal) distribution, so a few fast movers
    make most of the demand, as in a real ABC analysis.
    """
    profiles = []
    for category in categories:
        intermittent = bool(rng.random() < INTERMITTENT_SHARE)
        profiles.append(
            DemandProfile(
                category=category,
                base_rate=float(rng.lognormal(mean=0.0, sigma=1.3)),
                yearly_growth=float(rng.normal(0.08, 0.12)),
                season_strength=float(rng.uniform(0.6, 1.2)),
                intermittent=intermittent,
                promotions=() if intermittent else make_promotions(rng, start, days),
            )
        )
    return profiles


def make_promotions(rng: np.random.Generator, start: date, days: int) -> tuple[Promotion, ...]:
    """About 1-3 promotions per year, 3-10 days long, never overlapping."""
    count = int(rng.integers(1, 4)) * max(1, round(days / 365))
    promotions: list[Promotion] = []
    for _ in range(count * 3):  # a few tries in case of overlaps
        if len(promotions) == count:
            break
        length = int(rng.integers(3, 11))
        first = start + timedelta(days=int(rng.integers(0, max(1, days - length))))
        candidate = Promotion(
            first, first + timedelta(days=length - 1), float(rng.uniform(1.5, 3.0))
        )
        if all(candidate.end < p.start or candidate.start > p.end for p in promotions):
            promotions.append(candidate)
    return tuple(sorted(promotions, key=lambda p: p.start))


def demand_rate(profile: DemandProfile, day: date, day_index: int, days: int) -> float:
    """Expected units of the product ordered on that day."""
    rate = (
        profile.base_rate
        * weekday_factor(day)
        * season_factor(profile.category, day, profile.season_strength)
        * holiday_factor(day)
        * trend_factor(day_index, days, profile.yearly_growth)
        * profile.promotion_factor(day)
    )
    if profile.intermittent:
        # Same average, concentrated on few days: the classic "lumpy" demand.
        rate /= INTERMITTENT_SALE_DAY_PROBABILITY
    return rate


def sample_units(rng: np.random.Generator, profile: DemandProfile, rate: float) -> int:
    """Units actually ordered: Poisson noise around the rate."""
    if profile.intermittent and rng.random() >= INTERMITTENT_SALE_DAY_PROBABILITY:
        return 0
    return int(rng.poisson(rate))


# ============================================================================ suppliers
@dataclass(frozen=True)
class SupplierProfile:
    promised_lead_days: int  # what the supplier states
    reliability: float  # 0..1, share of deliveries on time in normal weeks


def make_supplier_profile(rng: np.random.Generator) -> SupplierProfile:
    return SupplierProfile(
        promised_lead_days=int(rng.choice([2, 3, 4, 5, 7, 7, 10, 14, 21, 28])),
        reliability=float(np.clip(rng.beta(9, 1.2), 0.55, 0.995)),
    )


def is_peak_season(day: date) -> bool:
    """Mid-November to the end of December: suppliers are busy and late more often."""
    return (day.month == 11 and day.day >= 15) or day.month == 12


def sample_lead_time(rng: np.random.Generator, supplier: SupplierProfile, ordered: date) -> int:
    """Days from ordering to delivery.

    On-time deliveries arrive around the promised time (sometimes a little early);
    late ones add a few days, more for long lead times. Reliability drops in peak
    season.
    """
    reliability = supplier.reliability - (0.15 if is_peak_season(ordered) else 0.0)
    promised = supplier.promised_lead_days
    if rng.random() < reliability:
        return max(1, promised - int(rng.integers(0, max(1, promised // 4) + 1)))
    lateness = 1 + int(rng.gamma(shape=2.0, scale=max(1.0, promised * 0.25)))
    return promised + lateness


# ============================================================================== delays
@dataclass(frozen=True)
class DelayFactors:
    units: int  # size of the order
    low_stock: bool  # some line could not be reserved at once
    occupancy: float  # how full the warehouse is, 0..1
    carrier_reliability: float  # 0..1
    peak_season: bool


def delay_probability(f: DelayFactors) -> float:
    """Probability that a shipment arrives late (a logistic model with known effects).

    About 5 % for a small order on a normal day; each risk factor raises it.
    """
    logit = (
        -3.0
        + 0.08 * max(0, f.units - 5)  # large orders
        + 1.2 * f.low_stock
        + 4.0 * max(0.0, f.occupancy - 0.75)  # a crowded warehouse is slow
        + 6.0 * (1.0 - f.carrier_reliability)
        + 0.7 * f.peak_season
    )
    return 1.0 / (1.0 + exp(-logit))


def sample_delay_days(rng: np.random.Generator) -> int:
    """How many days a late shipment is late: mostly 1-2, sometimes a week."""
    return int(rng.geometric(0.45))  # 1, 2, 3, ... days, each less likely


# ============================================================================== baskets
# Products of the key category are often bought with products of these categories.
COMPLEMENTS: dict[str, tuple[str, ...]] = {
    "Laptops": ("Accessories", "Accessories", "Electronics"),  # mouse, bag, dock, monitor
    "Electronics": ("Accessories",),
    "Tools & Hardware": ("Tools & Hardware",),  # drill with bits, screws
    "Automotive Parts": ("Automotive Parts",),  # oil with filter
    "Home & Kitchen": ("Home & Kitchen", "Food & Beverages"),
    "Office Supplies": ("Office Supplies",),
}
COMPANION_PROBABILITY = 0.35  # chance that an anchor product brings each companion


def make_basket_rules(
    rng: np.random.Generator, categories: Sequence[str], companions_per_product: int = 3
) -> dict[int, tuple[int, ...]]:
    """For each product (by index), the products often bought with it."""
    by_category: dict[str, list[int]] = {}
    for index, category in enumerate(categories):
        by_category.setdefault(category, []).append(index)
    rules: dict[int, tuple[int, ...]] = {}
    for index, category in enumerate(categories):
        pool = sorted(
            {
                other
                for target in COMPLEMENTS.get(category, ())
                for other in by_category.get(target, [])
                if other != index
            }
        )
        if pool:
            size = min(companions_per_product, len(pool))
            rules[index] = tuple(int(i) for i in rng.choice(pool, size=size, replace=False))
    return rules


def sample_companions(
    rng: np.random.Generator, anchor: int, rules: dict[int, tuple[int, ...]]
) -> list[int]:
    return [p for p in rules.get(anchor, ()) if rng.random() < COMPANION_PROBABILITY]


# ======================================================================= returns, damage
RETURN_PROBABILITY: dict[str, float] = {
    "Laptops": 0.06,
    "Electronics": 0.07,
    "Accessories": 0.05,
    "Home & Kitchen": 0.04,
    "Tools & Hardware": 0.03,
    "Automotive Parts": 0.04,
    "Office Supplies": 0.015,
    "Food & Beverages": 0.005,
}
RETURN_DAMAGED_SHARE = 0.25  # of returned units, how many come back damaged
PICK_DAMAGE_PROBABILITY = 0.002  # a unit found damaged while picking


def return_probability(category: str) -> float:
    return RETURN_PROBABILITY.get(category, 0.03)


# ====================================================================== demand volume
UNITS_PER_ORDER = 4.0  # average units in an order (about 2.5 lines x 1.6 units)


def expected_daily_units(profile: DemandProfile, start: date, days: int) -> float:
    """Average expected units per day over the history (every third day is enough:
    3 and 7 share no factor, so all weekdays are covered evenly)."""
    sample = range(0, days, 3)
    total = sum(demand_rate(profile, start + timedelta(days=i), i, days) for i in sample) / len(
        sample
    )
    if profile.intermittent:
        total *= INTERMITTENT_SALE_DAY_PROBABILITY  # rate is only realised on sale days
    return total


def scale_profiles(
    profiles: Sequence[DemandProfile], target_daily_units: float, start: date, days: int
) -> list[DemandProfile]:
    """Scale all base rates so the expected total demand per day hits the target."""
    current = sum(expected_daily_units(p, start, days) for p in profiles)
    factor = target_daily_units / current if current else 1.0
    return [replace(p, base_rate=p.base_rate * factor) for p in profiles]
