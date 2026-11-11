"""Each business pattern must really show up in sampled data (with a fixed seed)."""

from datetime import date, timedelta
from statistics import mean

import numpy as np
import pytest

from data_generation import patterns as p

START = date(2024, 11, 11)
DAYS = 730


def rng(seed: int = 1) -> np.random.Generator:
    return np.random.default_rng(seed)


def days_from(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


# ------------------------------------------------------------------------------ demand
def test_weekends_are_quiet() -> None:
    monday, saturday, sunday = date(2026, 11, 9), date(2026, 11, 14), date(2026, 11, 15)
    assert p.weekday_factor(monday) > p.weekday_factor(saturday) > p.weekday_factor(sunday)
    assert mean(p.WEEKDAY_FACTORS) == pytest.approx(0.92, abs=0.02)


@pytest.mark.parametrize(
    ("category", "high", "low"),
    [
        ("Laptops", 12, 2),  # Christmas vs February
        ("Home & Kitchen", 12, 6),
        ("Tools & Hardware", 5, 1),  # DIY season vs January
        ("Office Supplies", 9, 12),  # back to school vs December
        ("Automotive Parts", 10, 7),  # winter preparation vs summer
    ],
)
def test_categories_have_their_own_seasons(category: str, high: int, low: int) -> None:
    assert p.season_factor(category, date(2026, high, 15)) > p.season_factor(
        category, date(2026, low, 15)
    )


def test_seasonal_curves_average_one_and_strength_scales_them() -> None:
    for category, curve in p.SEASONAL_CURVES.items():
        assert len(curve) == 12
        assert mean(curve) == pytest.approx(1.0, abs=0.06), category
    december = date(2026, 12, 15)
    assert p.season_factor("Laptops", december, strength=0.0) == 1.0
    assert p.season_factor("Laptops", december, strength=0.5) == pytest.approx(1.3)
    assert p.season_factor("Unknown", december) == 1.0


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 11, 29)), (2025, date(2025, 11, 28)), (2026, date(2026, 11, 27))],
)
def test_black_friday(year: int, expected: date) -> None:
    assert p.black_friday(year) == expected
    assert expected.weekday() == 4  # a Friday


def test_holidays() -> None:
    assert p.holiday_factor(date(2025, 11, 28)) == 2.2  # Black Friday
    assert p.holiday_factor(date(2025, 12, 1)) == 2.2  # Cyber Monday
    assert p.holiday_factor(date(2025, 11, 25)) == 1.3  # the week before
    assert p.holiday_factor(date(2025, 12, 10)) == 1.2  # Christmas shopping
    assert p.holiday_factor(date(2025, 12, 25)) == 0.15
    assert p.holiday_factor(date(2026, 1, 1)) == 0.15
    assert p.holiday_factor(date(2025, 12, 24)) == 0.4
    assert p.holiday_factor(date(2025, 7, 15)) == 1.0


def test_trend() -> None:
    assert p.trend_factor(0, DAYS, 0.2) == pytest.approx(0.8, abs=0.01)
    assert p.trend_factor(DAYS - 1, DAYS, 0.2) == pytest.approx(1.2, abs=0.01)
    assert p.trend_factor(DAYS // 2, DAYS, 0.2) == pytest.approx(1.0, abs=0.01)
    assert p.trend_factor(DAYS - 1, DAYS, -5.0) == 0.1  # a steep decline never goes negative


def test_promotions_do_not_overlap_and_raise_demand() -> None:
    generator = rng()
    for _ in range(200):
        promotions = p.make_promotions(generator, START, DAYS)
        assert 2 <= len(promotions) <= 6  # 1-3 per year
        for a, b in zip(promotions, promotions[1:], strict=False):
            assert a.end < b.start
        for promotion in promotions:
            assert 3 <= (promotion.end - promotion.start).days + 1 <= 10
            assert 1.5 <= promotion.uplift <= 3.0
            assert START <= promotion.start <= promotion.end <= START + timedelta(days=DAYS)


def profiles(count: int = 2_000, seed: int = 1) -> list[p.DemandProfile]:
    categories = [p.CATEGORIES[i % len(p.CATEGORIES)] for i in range(count)]
    return p.make_demand_profiles(rng(seed), categories, START, DAYS)


def test_few_fast_movers_make_most_of_the_demand() -> None:
    rates = sorted((x.base_rate for x in profiles()), reverse=True)
    top_fifth = sum(rates[: len(rates) // 5]) / sum(rates)
    assert 0.55 < top_fifth < 0.85  # an ABC-like distribution


def test_some_products_are_intermittent() -> None:
    share = mean(x.intermittent for x in profiles())
    assert share == pytest.approx(p.INTERMITTENT_SHARE, abs=0.03)
    assert all(not x.promotions for x in profiles() if x.intermittent)


def simulate(profile: p.DemandProfile, seed: int = 3) -> dict[date, int]:
    generator = rng(seed)
    return {
        day: p.sample_units(generator, profile, p.demand_rate(profile, day, i, DAYS))
        for i, day in enumerate(days_from(START, DAYS))
    }


def steady(category: str = "Laptops", **changes: object) -> p.DemandProfile:
    values = dict(
        category=category,
        base_rate=20.0,
        yearly_growth=0.0,
        season_strength=1.0,
        intermittent=False,
    )
    values.update(changes)
    return p.DemandProfile(**values)


def test_sampled_demand_shows_weekly_and_yearly_patterns() -> None:
    sales = simulate(steady())
    weekday = mean(v for d, v in sales.items() if d.weekday() < 5)
    sunday = mean(v for d, v in sales.items() if d.weekday() == 6)
    assert sunday < 0.6 * weekday
    december = mean(v for d, v in sales.items() if d.month == 12)
    february = mean(v for d, v in sales.items() if d.month == 2)
    assert december > 1.6 * february


def test_sampled_demand_shows_trend_and_promotions() -> None:
    growing = simulate(steady(category="Office Supplies", yearly_growth=0.3))
    first_year = sum(v for d, v in growing.items() if d < START + timedelta(days=365))
    second_year = sum(v for d, v in growing.items() if d >= START + timedelta(days=365))
    assert second_year > 1.2 * first_year

    promotion = p.Promotion(date(2025, 6, 2), date(2025, 6, 8), 2.5)
    promoted = simulate(steady(promotions=(promotion,)))
    plain = simulate(steady())
    week = days_from(promotion.start, 7)
    assert sum(promoted[d] for d in week) > 2 * sum(plain[d] for d in week)


def test_intermittent_demand_is_lumpy_with_the_same_average() -> None:
    lumpy = simulate(steady(category="Unknown", intermittent=True, base_rate=2.0), seed=5)
    smooth = simulate(steady(category="Unknown", base_rate=2.0), seed=5)
    zero_days = mean(v == 0 for v in lumpy.values())
    assert zero_days > 0.8
    assert mean(lumpy.values()) == pytest.approx(mean(smooth.values()), rel=0.25)


def test_demand_is_reproducible() -> None:
    assert simulate(steady(), seed=9) == simulate(steady(), seed=9)
    assert simulate(steady(), seed=9) != simulate(steady(), seed=10)
    a = [x.base_rate for x in profiles(50, seed=4)]
    assert a == [x.base_rate for x in profiles(50, seed=4)]


# --------------------------------------------------------------------------- suppliers
def lead_times(supplier: p.SupplierProfile, day: date, n: int = 4_000) -> list[int]:
    generator = rng(11)
    return [p.sample_lead_time(generator, supplier, day) for _ in range(n)]


def test_lead_times_follow_the_promise_and_reliability() -> None:
    supplier = p.SupplierProfile(promised_lead_days=10, reliability=0.9)
    normal = lead_times(supplier, date(2026, 6, 10))
    assert min(normal) >= 1
    on_time = mean(t <= 10 for t in normal)
    assert on_time == pytest.approx(0.9, abs=0.02)
    assert 9 <= mean(normal) <= 11.5

    unreliable = lead_times(p.SupplierProfile(10, 0.6), date(2026, 6, 10))
    assert mean(t <= 10 for t in unreliable) == pytest.approx(0.6, abs=0.03)
    assert mean(unreliable) > mean(normal)


def test_suppliers_are_less_reliable_in_peak_season() -> None:
    supplier = p.SupplierProfile(promised_lead_days=7, reliability=0.9)
    june = lead_times(supplier, date(2026, 6, 10))
    december = lead_times(supplier, date(2026, 12, 10))
    assert mean(t <= 7 for t in december) == pytest.approx(0.75, abs=0.03)
    assert mean(december) > mean(june)
    assert p.is_peak_season(date(2026, 11, 15))
    assert not p.is_peak_season(date(2026, 11, 14))
    assert not p.is_peak_season(date(2027, 1, 2))


def test_supplier_profiles_are_varied() -> None:
    generator = rng()
    suppliers = [p.make_supplier_profile(generator) for _ in range(500)]
    assert len({s.promised_lead_days for s in suppliers}) >= 8
    assert all(0.55 <= s.reliability <= 0.995 for s in suppliers)
    assert mean(s.reliability for s in suppliers) == pytest.approx(0.88, abs=0.04)


# ------------------------------------------------------------------------------ delays
BASE = p.DelayFactors(
    units=3, low_stock=False, occupancy=0.5, carrier_reliability=1.0, peak_season=False
)


def with_(**changes: object) -> float:
    values = dict(BASE.__dict__)
    values.update(changes)
    return p.delay_probability(p.DelayFactors(**values))


def test_delay_risk_factors() -> None:
    base = p.delay_probability(BASE)
    assert base == pytest.approx(0.047, abs=0.005)  # about 5 %
    assert with_(units=40) > with_(units=10) > base
    assert with_(low_stock=True) > base
    assert with_(occupancy=0.95) > with_(occupancy=0.8) > base == with_(occupancy=0.7)
    assert with_(carrier_reliability=0.85) > base
    assert with_(peak_season=True) > base
    worst = with_(units=60, low_stock=True, occupancy=1.0, carrier_reliability=0.7)
    assert 0.9 < worst < 1.0


def test_delays_are_mostly_short() -> None:
    generator = rng()
    delays = [p.sample_delay_days(generator) for _ in range(5_000)]
    assert min(delays) == 1
    assert mean(d <= 2 for d in delays) == pytest.approx(0.70, abs=0.03)
    assert max(delays) >= 7


# ----------------------------------------------------------------------------- baskets
def test_basket_rules_link_complementary_categories() -> None:
    categories = ["Laptops", "Accessories", "Accessories", "Accessories", "Food & Beverages"]
    rules = p.make_basket_rules(rng(), categories, companions_per_product=2)
    assert len(rules[0]) == 2
    assert all(categories[i] == "Accessories" for i in rules[0])
    assert 4 not in rules  # food has no companions
    assert all(i not in rules.get(i, ()) for i in range(len(categories)))


def test_companions_are_bought_with_the_expected_probability() -> None:
    rules = {0: (1, 2)}
    generator = rng()
    picks = [p.sample_companions(generator, 0, rules) for _ in range(5_000)]
    share = mean(1 in pick for pick in picks)
    assert share == pytest.approx(p.COMPANION_PROBABILITY, abs=0.02)
    assert p.sample_companions(generator, 7, rules) == []


# ----------------------------------------------------------------------------- returns
def test_return_rates_differ_by_category() -> None:
    assert p.return_probability("Electronics") > p.return_probability("Office Supplies")
    assert p.return_probability("Food & Beverages") < 0.01
    assert p.return_probability("Unknown") == 0.03
    assert set(p.RETURN_PROBABILITY) == set(p.CATEGORIES)


def test_sampled_demand_peaks_on_black_friday_and_stops_at_christmas() -> None:
    sales = simulate(steady(category="Unknown", base_rate=40.0))
    black_friday = p.black_friday(2025)
    other_fridays = [
        v for d, v in sales.items() if d.weekday() == 4 and d.month in (9, 10) and d.year == 2025
    ]
    assert sales[black_friday] > 1.8 * mean(other_fridays)
    assert sales[date(2025, 12, 25)] < 0.3 * mean(other_fridays)


def test_same_category_companions_never_include_the_product_itself() -> None:
    categories = ["Tools & Hardware"] * 3
    for seed in range(20):
        rules = p.make_basket_rules(rng(seed), categories, companions_per_product=2)
        for index, companions in rules.items():
            assert index not in companions
            assert len(companions) == 2
