"""Categories, products, suppliers, supplier offers, customers and carriers.

Products get a demand profile (patterns.py) scaled so the whole catalog sells about
`orders x UNITS_PER_ORDER` units over the history; their minimum stock follows from it.
Suppliers get a true behaviour (promised lead time, reliability); the stored
reliability rating is a noisy estimate of it, as in real life.
"""

from decimal import ROUND_HALF_UP, Decimal
from math import ceil

import numpy as np

from app.models import Carrier, Category, Customer, Product, Supplier, SupplierProduct
from data_generation import catalog_data as data
from data_generation.context import (
    CarrierInfo,
    CustomerInfo,
    GenerationContext,
    ProductInfo,
    SupplierInfo,
)
from data_generation.patterns import (
    CATEGORIES,
    UNITS_PER_ORDER,
    make_demand_profiles,
    make_supplier_profile,
    scale_profiles,
)

COVER_DAYS_MIN = 10  # minimum stock covers about ten days of average demand
COVER_DAYS_MAX = 45
SECOND_SOURCE_SHARE = 0.3  # products also offered by a second supplier


def generate_master_data(ctx: GenerationContext) -> None:
    category_ids = _categories(ctx)
    _suppliers(ctx)
    _products(ctx, category_ids)
    _supplier_offers(ctx)
    _customers(ctx)
    _carriers(ctx)


def _stamp(ctx: GenerationContext) -> dict[str, object]:
    return {"created_at": ctx.start_time, "updated_at": ctx.start_time}


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ean13(sequence: int) -> str:
    """A valid EAN-13 from a running number (prefix 400-440: Germany)."""
    body = f"400{sequence:09d}"
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


# --------------------------------------------------------------------------- categories
def _categories(ctx: GenerationContext) -> dict[str, int]:
    names = ["Electronics", *[c for c in CATEGORIES if c != "Electronics"]]
    ids = {name: index for index, name in enumerate(names, start=1)}
    ctx.writer.insert(
        Category.__table__,
        (
            {
                "id": ids[name],
                "name": name,
                "description": data.CATEGORY_DESCRIPTIONS[name],
                "parent_id": ids.get(data.PARENT_CATEGORY.get(name, "")),
                "is_active": True,
                **_stamp(ctx),
            }
            for name in names
        ),
    )
    return ids


# ---------------------------------------------------------------------------- suppliers
def _suppliers(ctx: GenerationContext) -> None:
    rng = ctx.rng("suppliers")
    count = ctx.config.suppliers
    # Every category gets at least one supplier; each supplier serves 1-2 categories.
    served = [[CATEGORIES[i % len(CATEGORIES)]] for i in range(count)]
    for categories in served:
        if rng.random() < 0.4:
            extra = str(rng.choice(CATEGORIES))
            if extra not in categories:
                categories.append(extra)

    rows, used_names = [], set()
    for index in range(count):
        country, form, extra_days = data.SUPPLIER_COUNTRIES[
            int(rng.integers(len(data.SUPPLIER_COUNTRIES)))
        ]
        name = f"{rng.choice(data.SUPPLIER_WORDS_1)} {rng.choice(data.SUPPLIER_WORDS_2)} {form}"
        if name in used_names:
            name = f"{name} ({index + 1})"
        used_names.add(name)
        profile = make_supplier_profile(rng)
        if extra_days:  # overseas: long promised lead times
            profile = type(profile)(
                promised_lead_days=max(profile.promised_lead_days, extra_days),
                reliability=profile.reliability,
            )
        code = f"SUP-{index + 1:03d}"
        rating = float(np.clip(profile.reliability + rng.normal(0, 0.04), 0, 1))
        rows.append(
            {
                "id": index + 1,
                "code": code,
                "name": name,
                "contact_name": f"{rng.choice(data.FIRST_NAMES)} {rng.choice(data.LAST_NAMES)}",
                "email": f"sales@{code.lower()}.example",
                "phone": f"+49 {int(rng.integers(30, 990))} {int(rng.integers(100000, 999999))}",
                "address": None,
                "country": country,
                "lead_time_days": profile.promised_lead_days,
                "reliability_score": Decimal(f"{rating:.2f}"),
                "is_active": True,
                **_stamp(ctx),
            }
        )
        ctx.suppliers.append(
            SupplierInfo(id=index + 1, code=code, categories=tuple(served[index]), profile=profile)
        )
    ctx.writer.insert(Supplier.__table__, rows)


# ----------------------------------------------------------------------------- products
def category_plan(products: int) -> list[str]:
    """Category of every product: shares from CATEGORY_SPECS, at least one each."""
    shares = {name: spec[1] for name, spec in data.CATEGORY_SPECS.items()}
    counts = {name: max(1, int(products * share)) for name, share in shares.items()}
    names = sorted(shares, key=lambda n: -shares[n])
    index = 0
    while sum(counts.values()) < products:  # hand out the remainder by share
        counts[names[index % len(names)]] += 1
        index += 1
    while sum(counts.values()) > products:
        largest = max(counts, key=lambda n: counts[n])
        counts[largest] -= 1
    return [name for name in CATEGORIES for _ in range(counts[name])]


def _round_price(value: float) -> Decimal:
    """Shop prices end in .99 (or .90 for small amounts)."""
    return _money(int(value) + (0.90 if value < 10 else 0.99))


def _products(ctx: GenerationContext, category_ids: dict[str, int]) -> None:
    rng = ctx.rng("catalog")
    config = ctx.config
    categories = category_plan(config.products)
    order = rng.permutation(len(categories))  # mix categories over the id range
    categories = [categories[i] for i in order]

    profiles = make_demand_profiles(rng, categories, config.start_date, config.days)
    profiles = scale_profiles(
        profiles, config.orders_per_day * UNITS_PER_ORDER, config.start_date, config.days
    )
    by_category: dict[str, list[SupplierInfo]] = {}
    for supplier in ctx.suppliers:
        for category in supplier.categories:
            by_category.setdefault(category, []).append(supplier)

    rows, sequence = [], {name: 0 for name in CATEGORIES}
    for index, (category, profile) in enumerate(zip(categories, profiles, strict=True)):
        prefix, _share, cost_share, brands = data.CATEGORY_SPECS[category]
        name, weight_range, size, price_range, storage = data.PRODUCT_TEMPLATES[category][
            int(rng.integers(len(data.PRODUCT_TEMPLATES[category])))
        ]
        sequence[category] += 1
        sku = f"{prefix}-{sequence[category]:05d}"
        brand = str(rng.choice(brands))
        variant = str(rng.choice(data.VARIANTS))
        jitter = rng.uniform(0.92, 1.08, size=3)
        length, width, height = (
            Decimal(f"{max(0.5, s * j):.1f}") for s, j in zip(size, jitter, strict=True)
        )
        weight = Decimal(f"{rng.uniform(*weight_range):.3f}")
        price = _round_price(float(rng.uniform(*price_range)))
        cost = _money(float(price) * rng.uniform(*cost_share))
        daily = profile.base_rate * 0.92  # about the average expected daily units
        min_stock = max(1, ceil(daily * COVER_DAYS_MIN))
        max_stock = max(min_stock + 2, ceil(daily * COVER_DAYS_MAX))
        preferred = by_category[category][int(rng.integers(len(by_category[category])))]
        product_id = index + 1
        rows.append(
            {
                "id": product_id,
                "sku": sku,
                "name": f"{brand} {name} {variant}",
                "description": f"{name} by {brand}, {variant} model",
                "category_id": category_ids[category],
                "brand": brand,
                "unit_price": price,
                "unit_cost": cost,
                "weight_kg": weight,
                "length_cm": length,
                "width_cm": width,
                "height_cm": height,
                "barcode": ean13(product_id),
                "min_stock": min_stock,
                "max_stock": max_stock,
                "default_supplier_id": preferred.id,
                "is_active": True,
                **_stamp(ctx),
            }
        )
        ctx.products.append(
            ProductInfo(
                id=product_id,
                sku=sku,
                category=category,
                unit_price=price,
                unit_cost=cost,
                weight_kg=weight,
                volume_cm3=length * width * height,
                min_stock=min_stock,
                max_stock=max_stock,
                storage=storage,
                profile=profile,
                supplier_ids=[preferred.id],
            )
        )
    ctx.writer.insert(Product.__table__, rows)


def _supplier_offers(ctx: GenerationContext) -> None:
    rng = ctx.rng("suppliers")
    by_category: dict[str, list[SupplierInfo]] = {}
    for supplier in ctx.suppliers:
        for category in supplier.categories:
            by_category.setdefault(category, []).append(supplier)
    suppliers = {s.id: s for s in ctx.suppliers}

    rows = []
    for product in ctx.products:
        others = [s for s in by_category[product.category] if s.id != product.supplier_ids[0]]
        if others and rng.random() < SECOND_SOURCE_SHARE:
            product.supplier_ids.append(others[int(rng.integers(len(others)))].id)
        for rank, supplier_id in enumerate(product.supplier_ids):
            supplier = suppliers[supplier_id]
            markup = 1.0 if rank == 0 else float(rng.uniform(1.03, 1.10))
            cost = _money(float(product.unit_cost) * markup)
            product.offer_costs[supplier_id] = cost
            product.min_order_qty = max(1, product.min_stock // 2)
            rows.append(
                {
                    "supplier_id": supplier_id,
                    "product_id": product.id,
                    "supplier_sku": f"{supplier.code[-3:]}-{product.sku}",
                    "unit_cost": cost,
                    "lead_time_days": None,  # the supplier's usual lead time
                    "min_order_qty": product.min_order_qty,
                    "is_preferred": rank == 0,
                    **_stamp(ctx),
                }
            )
    ctx.writer.insert(SupplierProduct.__table__, rows)


# ---------------------------------------------------------------------------- customers
def _customers(ctx: GenerationContext) -> None:
    rng = ctx.rng("customers")
    rows = []
    for index in range(ctx.config.customers):
        business = rng.random() < 0.6
        last = str(rng.choice(data.LAST_NAMES))
        if business:
            name = f"{last} {rng.choice(data.BUSINESS_KINDS)} {rng.choice(data.BUSINESS_FORMS)}"
            # A few large accounts order very often (heavy-tailed activity).
            activity = float(rng.pareto(1.5) + 1.0)
        else:
            name = f"{rng.choice(data.FIRST_NAMES)} {last}"
            activity = float(rng.uniform(0.2, 1.0))
        code = f"CUST-{index + 1:05d}"
        postal, city, country = data.CITIES[int(rng.integers(len(data.CITIES)))]
        rows.append(
            {
                "id": index + 1,
                "code": code,
                "name": name,
                "customer_type": "business" if business else "consumer",
                "email": f"{code.lower()}@customers.example",
                "phone": f"+49 {int(rng.integers(30, 990))} {int(rng.integers(100000, 9999999))}",
                "address_line": f"{rng.choice(data.STREETS)} {int(rng.integers(1, 120))}",
                "postal_code": postal,
                "city": city,
                "country": country,
                "user_id": None,
                "is_active": True,
                **_stamp(ctx),
            }
        )
        row = rows[-1]
        ctx.customers.append(
            CustomerInfo(
                id=index + 1,
                customer_type=row["customer_type"],
                activity=activity,
                name=row["name"],
                address_line=row["address_line"],
                postal_code=row["postal_code"],
                city=row["city"],
                country=row["country"],
            )
        )
    ctx.writer.insert(Customer.__table__, rows)


# ----------------------------------------------------------------------------- carriers
def _carriers(ctx: GenerationContext) -> None:
    if ctx.config.carriers > len(data.CARRIERS):
        raise ValueError(f"at most {len(data.CARRIERS)} carriers are available")
    rows = []
    for index, (code, name, transit, reliability) in enumerate(
        data.CARRIERS[: ctx.config.carriers]
    ):
        rows.append(
            {
                "id": index + 1,
                "code": code,
                "name": name,
                "tracking_url_template": f"https://track.example.com/{code.lower()}/"
                "{tracking_number}",
                "default_transit_days": transit,
                "is_active": True,
                **_stamp(ctx),
            }
        )
        ctx.carriers.append(
            CarrierInfo(id=index + 1, code=code, transit_days=transit, reliability=reliability)
        )
    ctx.writer.insert(Carrier.__table__, rows)
