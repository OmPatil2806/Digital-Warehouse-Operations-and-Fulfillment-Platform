"""Load a small, realistic demo dataset (users, catalog, suppliers, warehouse layout).

Run from the project root, after `alembic upgrade head` (virtual environment active):

    python scripts/seed_database.py           # add demo data (existing records are kept)
    python scripts/seed_database.py --reset   # delete demo data first, then load it again

Everything is created through the application's services, so all business rules apply.
Running it twice is safe: records that already exist (same email, code, SKU or name) are
skipped. The large synthetic dataset for machine learning comes in Phase 7.

Demo logins (local development only):
    admin@example.com, manager@example.com, staff@example.com, customer@example.com
    password: Demo-pass-123
"""

# The data tables below keep one record per line for readability.
# ruff: noqa: E501

import argparse
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

# Make the backend package (`app`) importable when running from the project root.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, func, inspect, select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import INSECURE_SECRET_ALLOWED_ENVS, get_settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models.catalog import Category, Product, Supplier, SupplierProduct  # noqa: E402
from app.models.user import RoleName, User  # noqa: E402
from app.models.warehouse import Bin, Rack, Shelf, Warehouse, Zone  # noqa: E402
from app.schemas.catalog import (  # noqa: E402
    CategoryCreate,
    ProductCreate,
    SupplierCreate,
    SupplierProductCreate,
)
from app.schemas.user import UserCreate  # noqa: E402
from app.schemas.warehouse import GenerateLayoutRequest, WarehouseCreate, ZoneCreate  # noqa: E402
from app.services.catalog_service import (  # noqa: E402
    CategoryService,
    ProductService,
    SupplierProductService,
    SupplierService,
)
from app.services.user_service import UserService  # noqa: E402
from app.services.warehouse_service import WarehouseService  # noqa: E402

SessionFactory = Callable[[], AbstractContextManager[Session]]

DEMO_PASSWORD = "Demo-pass-123"

# ------------------------------------------------------------------------------ data
# fmt: off
DEMO_USERS = [
    ("admin@example.com", "Ada Admin", RoleName.ADMIN),
    ("manager@example.com", "Maya Manager", RoleName.MANAGER),
    ("staff@example.com", "Sam Staff", RoleName.STAFF),
    ("customer@example.com", "Chris Customer", RoleName.CUSTOMER),
]

# (name, parent name, description)
CATEGORIES = [
    ("Electronics", None, "Consumer electronics"),
    ("Laptops", "Electronics", "Notebooks and ultrabooks"),
    ("Accessories", "Electronics", "Mice, keyboards, cables and chargers"),
    ("Office Supplies", None, "Paper, writing and desk equipment"),
    ("Automotive Parts", None, "Spare parts and car care"),
    ("Tools & Hardware", None, "Hand tools, power tools and fasteners"),
    ("Home & Kitchen", None, "Small appliances and kitchenware"),
    ("Food & Beverages", None, "Chilled and ambient groceries"),
]

# (code, name, country, lead time days, reliability)
SUPPLIERS = [
    ("SUP-001", "Nordtech Distribution GmbH", "Germany", 5, "0.97"),
    ("SUP-002", "Pacific Components Ltd", "Taiwan", 21, "0.91"),
    ("SUP-003", "OfficeLine BV", "Netherlands", 4, "0.98"),
    ("SUP-004", "AutoParts Europa SpA", "Italy", 9, "0.89"),
    ("SUP-005", "Steelcraft Tools AB", "Sweden", 7, "0.95"),
    ("SUP-006", "HomeGoods Polska Sp. z o.o.", "Poland", 6, "0.93"),
    ("SUP-007", "FreshChain Foods SAS", "France", 2, "0.96"),
    ("SUP-008", "Iberia Logistics SL", "Spain", 8, "0.88"),
    ("SUP-009", "Danube Electronics Kft", "Hungary", 10, "0.92"),
    ("SUP-010", "Baltic Wholesale UAB", "Lithuania", 12, "0.85"),
]

# (sku, name, category, brand, price, cost, weight kg, L, W, H cm, min, max, supplier)
PRODUCTS = [
    ("LAP-1401", "Laptop 14\" Business", "Laptops", "Vantec", "899.00", "640.00", "1.450", "33.0", "23.5", "2.0", 5, 40, "SUP-001"),
    ("LAP-1501", "Laptop 15\" Performance", "Laptops", "Vantec", "1299.00", "940.00", "2.100", "36.0", "25.0", "2.3", 3, 25, "SUP-001"),
    ("LAP-1301", "Ultrabook 13\"", "Laptops", "Lumio", "1099.00", "790.00", "1.150", "30.5", "21.5", "1.5", 3, 25, "SUP-009"),
    ("LAP-1601", "Laptop 16\" Creator", "Laptops", "Lumio", "1899.00", "1420.00", "2.400", "36.5", "25.5", "2.0", 2, 15, "SUP-009"),
    ("ACC-MOU1", "Wireless Mouse", "Accessories", "Clicky", "24.90", "9.50", "0.090", "11.0", "6.5", "4.0", 30, 300, "SUP-002"),
    ("ACC-KEY1", "Mechanical Keyboard", "Accessories", "Clicky", "89.00", "41.00", "0.950", "44.0", "14.0", "4.0", 10, 120, "SUP-002"),
    ("ACC-USB1", "USB-C Cable 1 m", "Accessories", "Linkr", "9.90", "2.10", "0.040", "12.0", "8.0", "2.0", 50, 600, "SUP-002"),
    ("ACC-CHG1", "65 W USB-C Charger", "Accessories", "Linkr", "39.00", "16.00", "0.180", "7.0", "7.0", "3.0", 20, 250, "SUP-009"),
    ("ACC-HUB1", "USB-C Docking Hub", "Accessories", "Linkr", "69.00", "30.00", "0.210", "12.0", "5.0", "2.0", 15, 150, "SUP-001"),
    ("ACC-HDS1", "Noise-cancelling Headset", "Accessories", "Sonora", "149.00", "78.00", "0.320", "20.0", "18.0", "8.0", 10, 100, "SUP-009"),
    ("ACC-WEB1", "Full HD Webcam", "Accessories", "Sonora", "59.00", "26.00", "0.160", "10.0", "6.0", "6.0", 10, 120, "SUP-002"),
    ("ACC-MON1", "27\" Monitor", "Electronics", "Vantec", "279.00", "190.00", "5.800", "68.0", "45.0", "15.0", 4, 30, "SUP-001"),
    ("ELE-SPK1", "Bluetooth Speaker", "Electronics", "Sonora", "79.00", "35.00", "0.600", "18.0", "8.0", "8.0", 10, 100, "SUP-009"),
    ("ELE-TAB1", "10\" Tablet", "Electronics", "Lumio", "349.00", "245.00", "0.480", "25.0", "17.0", "1.0", 5, 50, "SUP-002"),
    ("OFF-PAP1", "Copy Paper A4 80 g (500 sheets)", "Office Supplies", "PaperPro", "5.49", "2.60", "2.500", "30.0", "21.0", "5.0", 100, 1500, "SUP-003"),
    ("OFF-PEN1", "Ballpoint Pens Blue (10 pack)", "Office Supplies", "Scriba", "4.99", "1.40", "0.120", "15.0", "8.0", "2.0", 80, 800, "SUP-003"),
    ("OFF-NOT1", "Notebook A5 Ruled", "Office Supplies", "Scriba", "3.49", "1.10", "0.250", "21.0", "15.0", "1.5", 60, 600, "SUP-003"),
    ("OFF-STP1", "Desk Stapler", "Office Supplies", "OfficeLine", "12.90", "5.20", "0.400", "16.0", "6.0", "8.0", 20, 200, "SUP-003"),
    ("OFF-FLD1", "Lever Arch File (5 pack)", "Office Supplies", "OfficeLine", "14.90", "6.80", "2.100", "32.0", "29.0", "8.0", 25, 250, "SUP-008"),
    ("OFF-CHR1", "Ergonomic Office Chair", "Office Supplies", "SitWell", "229.00", "135.00", "15.500", "70.0", "65.0", "50.0", 2, 20, "SUP-006"),
    ("OFF-LMP1", "LED Desk Lamp", "Office Supplies", "Lumen", "34.90", "14.00", "0.900", "40.0", "15.0", "10.0", 10, 100, "SUP-006"),
    ("AUT-BRK1", "Brake Pad Set Front", "Automotive Parts", "Stopline", "49.90", "22.00", "2.300", "22.0", "15.0", "8.0", 15, 150, "SUP-004"),
    ("AUT-FIL1", "Oil Filter", "Automotive Parts", "Filtra", "8.90", "3.10", "0.350", "10.0", "10.0", "12.0", 40, 400, "SUP-004"),
    ("AUT-FIL2", "Cabin Air Filter", "Automotive Parts", "Filtra", "14.90", "5.40", "0.250", "25.0", "20.0", "4.0", 30, 300, "SUP-004"),
    ("AUT-BAT1", "Car Battery 12 V 70 Ah", "Automotive Parts", "Voltix", "119.00", "72.00", "18.500", "28.0", "17.5", "19.0", 4, 40, "SUP-004"),
    ("AUT-WIP1", "Wiper Blades (pair)", "Automotive Parts", "ClearView", "19.90", "7.20", "0.450", "65.0", "8.0", "4.0", 20, 200, "SUP-008"),
    ("AUT-OIL1", "Engine Oil 5W-30 5 L", "Automotive Parts", "Lubrix", "39.90", "21.00", "4.600", "25.0", "13.0", "30.0", 20, 200, "SUP-008"),
    ("AUT-SPK1", "Spark Plugs (4 pack)", "Automotive Parts", "Voltix", "24.90", "9.80", "0.240", "12.0", "8.0", "4.0", 25, 250, "SUP-004"),
    ("TOO-DRL1", "Cordless Drill 18 V", "Tools & Hardware", "Steelcraft", "129.00", "74.00", "1.800", "30.0", "25.0", "9.0", 6, 60, "SUP-005"),
    ("TOO-HAM1", "Claw Hammer 450 g", "Tools & Hardware", "Steelcraft", "16.90", "6.50", "0.700", "33.0", "13.0", "3.0", 15, 150, "SUP-005"),
    ("TOO-SCR1", "Screwdriver Set (12 pcs)", "Tools & Hardware", "Steelcraft", "29.90", "11.40", "1.100", "30.0", "20.0", "5.0", 12, 120, "SUP-005"),
    ("TOO-SAW1", "Hand Saw 500 mm", "Tools & Hardware", "Steelcraft", "19.90", "7.80", "0.600", "62.0", "14.0", "2.0", 10, 100, "SUP-005"),
    ("TOO-TAP1", "Measuring Tape 5 m", "Tools & Hardware", "Measura", "9.90", "3.20", "0.220", "8.0", "8.0", "4.0", 30, 300, "SUP-010"),
    ("TOO-SCW1", "Wood Screws Assortment (500)", "Tools & Hardware", "Fastix", "14.90", "4.90", "1.400", "20.0", "15.0", "6.0", 20, 200, "SUP-010"),
    ("TOO-LAD1", "Aluminium Step Ladder 3 Steps", "Tools & Hardware", "Climbex", "59.00", "31.00", "4.800", "110.0", "45.0", "8.0", 3, 30, "SUP-010"),
    ("HOM-KET1", "Electric Kettle 1.7 L", "Home & Kitchen", "Casa", "34.90", "15.80", "1.200", "24.0", "17.0", "25.0", 10, 100, "SUP-006"),
    ("HOM-TOA1", "2-Slice Toaster", "Home & Kitchen", "Casa", "39.90", "17.50", "1.600", "30.0", "18.0", "20.0", 8, 80, "SUP-006"),
    ("HOM-PAN1", "Non-stick Frying Pan 28 cm", "Home & Kitchen", "Cucina", "29.90", "12.30", "1.100", "50.0", "29.0", "6.0", 12, 120, "SUP-006"),
    ("HOM-KNF1", "Chef's Knife 20 cm", "Home & Kitchen", "Cucina", "49.90", "19.00", "0.300", "35.0", "6.0", "3.0", 10, 100, "SUP-008"),
    ("HOM-BLN1", "Blender 1.5 L", "Home & Kitchen", "Casa", "69.00", "33.00", "3.200", "22.0", "22.0", "42.0", 6, 60, "SUP-006"),
    ("HOM-MUG1", "Ceramic Mugs (6 pack)", "Home & Kitchen", "Cucina", "19.90", "7.10", "2.400", "30.0", "20.0", "12.0", 15, 150, "SUP-010"),
    ("HOM-VAC1", "Cordless Vacuum Cleaner", "Home & Kitchen", "Casa", "199.00", "118.00", "3.400", "115.0", "26.0", "22.0", 3, 30, "SUP-001"),
    ("FOO-MLK1", "Fresh Milk 1 L (12 pack)", "Food & Beverages", "DairyBest", "14.40", "9.60", "12.600", "30.0", "22.0", "26.0", 30, 300, "SUP-007"),
    ("FOO-YOG1", "Greek Yogurt 500 g (8 pack)", "Food & Beverages", "DairyBest", "21.60", "13.20", "4.200", "28.0", "14.0", "10.0", 20, 200, "SUP-007"),
    ("FOO-CHE1", "Cheddar Cheese 400 g (10 pack)", "Food & Beverages", "DairyBest", "39.90", "25.00", "4.100", "30.0", "20.0", "8.0", 15, 150, "SUP-007"),
    ("FOO-JUI1", "Orange Juice 1 L (6 pack)", "Food & Beverages", "SunPress", "11.94", "6.90", "6.400", "24.0", "16.0", "25.0", 25, 250, "SUP-007"),
    ("FOO-WAT1", "Mineral Water 1.5 L (6 pack)", "Food & Beverages", "Alpina", "4.74", "2.20", "9.200", "26.0", "17.0", "32.0", 40, 400, "SUP-008"),
    ("FOO-COF1", "Ground Coffee 1 kg", "Food & Beverages", "Roastery", "15.90", "8.40", "1.050", "20.0", "12.0", "8.0", 30, 300, "SUP-008"),
    ("FOO-PAS1", "Pasta 500 g (12 pack)", "Food & Beverages", "Cucina", "13.08", "6.60", "6.300", "35.0", "25.0", "15.0", 25, 250, "SUP-010"),
    ("FOO-CHO1", "Dark Chocolate 100 g (20 pack)", "Food & Beverages", "Cacao Co", "29.80", "14.50", "2.200", "25.0", "15.0", "10.0", 20, 200, "SUP-007"),
]

# Second (more expensive) source for some products, so products have several suppliers.
SECOND_SOURCES = {
    "LAP-1401": "SUP-009",
    "ACC-MOU1": "SUP-009",
    "ACC-USB1": "SUP-001",
    "OFF-PAP1": "SUP-008",
    "AUT-FIL1": "SUP-008",
    "AUT-OIL1": "SUP-004",
    "TOO-DRL1": "SUP-001",
    "HOM-KET1": "SUP-010",
    "FOO-WAT1": "SUP-010",
    "FOO-COF1": "SUP-007",
}

WAREHOUSE = ("WH01", "Main Distribution Centre", "Logistikstraße 12, 70173 Stuttgart, Germany")

# (code, name, type, racks, shelves per rack, bins per shelf, max kg, max cm³, first distance m)
ZONES = [
    ("ZA", "Picking A (fast movers)", "picking", 8, 4, 6, "30", 120_000, "4"),
    ("ZB", "Bulk storage", "bulk", 4, 3, 4, "800", 1_500_000, "25"),
    ("ZC", "Cold storage", "cold", 2, 3, 4, "150", 300_000, "18"),
    ("ZR", "Returns", "returns", 1, 2, 5, "100", 250_000, "2"),
]

# fmt: on


def ean13(sequence: int) -> str:
    """A valid EAN-13 barcode (with check digit) from a running number."""
    body = f"400{sequence:09d}"  # 400-440 = GS1 Germany prefix range
    total = sum(int(digit) * (3 if i % 2 else 1) for i, digit in enumerate(body))
    return body + str((10 - total % 10) % 10)


# ---------------------------------------------------------------------------- report
@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, *, created: bool) -> None:
        target = self.created if created else self.skipped
        target[kind] = target.get(kind, 0) + 1

    def lines(self) -> list[str]:
        kinds = list(dict.fromkeys([*self.created, *self.skipped]))
        return [
            f"  {kind:<18} created {self.created.get(kind, 0):>4}   "
            f"already there {self.skipped.get(kind, 0):>4}"
            for kind in kinds
        ]


class SeedError(Exception):
    """A problem the user can fix; shown without a traceback."""


# ---------------------------------------------------------------------------- seeding
def seed(db: Session) -> SeedReport:
    """Create all demo data that does not exist yet. Safe to run repeatedly."""
    if not inspect(db.get_bind()).has_table("bins"):
        raise SeedError(
            "Database tables are missing. Run `alembic upgrade head` in backend/ first."
        )
    report = SeedReport()
    _seed_users(db, report)
    categories = _seed_categories(db, report)
    suppliers = _seed_suppliers(db, report)
    products = _seed_products(db, report, categories, suppliers)
    _seed_supplier_links(db, report, products, suppliers)
    _seed_layout(db, report)
    return report


def _seed_users(db: Session, report: SeedReport) -> None:
    service = UserService(db)
    for email, name, role in DEMO_USERS:
        exists = service.users.get_by_email(email) is not None
        if not exists:
            service.create_user(
                UserCreate(email=email, full_name=name, password=DEMO_PASSWORD, roles=[role])
            )
        report.add("users", created=not exists)


def _seed_categories(db: Session, report: SeedReport) -> dict[str, Category]:
    service = CategoryService(db)
    by_name = {c.name: c for c in db.scalars(select(Category))}
    for name, parent, description in CATEGORIES:  # parents are listed before children
        exists = name in by_name
        if not exists:
            by_name[name] = service.create(
                CategoryCreate(
                    name=name,
                    description=description,
                    parent_id=by_name[parent].id if parent else None,
                )
            )
        report.add("categories", created=not exists)
    return by_name


def _seed_suppliers(db: Session, report: SeedReport) -> dict[str, Supplier]:
    service = SupplierService(db)
    by_code = {s.code: s for s in db.scalars(select(Supplier))}
    for code, name, country, lead_time, reliability in SUPPLIERS:
        exists = code in by_code
        if not exists:
            slug = code.lower().replace("-", "")
            by_code[code] = service.create(
                SupplierCreate(
                    code=code,
                    name=name,
                    country=country,
                    email=f"orders.{slug}@example.com",
                    lead_time_days=lead_time,
                    reliability_score=Decimal(reliability),
                )
            )
        report.add("suppliers", created=not exists)
    return by_code


def _seed_products(
    db: Session,
    report: SeedReport,
    categories: dict[str, Category],
    suppliers: dict[str, Supplier],
) -> dict[str, Product]:
    service = ProductService(db)
    by_sku = {p.sku: p for p in db.scalars(select(Product))}
    for number, row in enumerate(PRODUCTS, start=1):
        sku, name, category, brand, price, cost, weight, length, width, height = row[:10]
        min_stock, max_stock, supplier_code = row[10:]
        exists = sku in by_sku
        if not exists:
            by_sku[sku] = service.create(
                ProductCreate(
                    sku=sku,
                    name=name,
                    category_id=categories[category].id,
                    brand=brand,
                    unit_price=Decimal(price),
                    unit_cost=Decimal(cost),
                    weight_kg=Decimal(weight),
                    length_cm=Decimal(length),
                    width_cm=Decimal(width),
                    height_cm=Decimal(height),
                    barcode=ean13(number),
                    min_stock=min_stock,
                    max_stock=max_stock,
                    default_supplier_id=suppliers[supplier_code].id,
                )
            )
        report.add("products", created=not exists)
    return by_sku


def _seed_supplier_links(
    db: Session,
    report: SeedReport,
    products: dict[str, Product],
    suppliers: dict[str, Supplier],
) -> None:
    service = SupplierProductService(db)
    existing = {(link.supplier_id, link.product_id) for link in db.scalars(select(SupplierProduct))}

    def link(supplier: Supplier, product: Product, cost: Decimal, preferred: bool) -> None:
        exists = (supplier.id, product.id) in existing
        if not exists:
            service.add(
                supplier.id,
                SupplierProductCreate(
                    product_id=product.id,
                    supplier_sku=f"{supplier.code[-3:]}-{product.sku}",
                    unit_cost=cost,
                    min_order_qty=max(1, product.min_stock // 2),
                    is_preferred=preferred,
                ),
            )
        report.add("supplier offers", created=not exists)

    for row in PRODUCTS:
        sku, cost, supplier_code = row[0], Decimal(row[5]), row[12]
        product = products[sku]
        link(suppliers[supplier_code], product, cost, preferred=True)
        if sku in SECOND_SOURCES:
            second_cost = (cost * Decimal("1.08")).quantize(Decimal("0.01"))  # 8 % dearer
            link(suppliers[SECOND_SOURCES[sku]], product, second_cost, preferred=False)


def _seed_layout(db: Session, report: SeedReport) -> None:
    service = WarehouseService(db)
    code, name, address = WAREHOUSE
    warehouse = db.scalars(select(Warehouse).where(Warehouse.code == code)).first()
    report.add("warehouses", created=warehouse is None)
    if warehouse is None:
        warehouse = service.create_warehouse(WarehouseCreate(code=code, name=name, address=address))

    for zone_code, zone_name, zone_type, racks, shelves, bins, kg, cm3, distance in ZONES:
        zone = db.scalars(
            select(Zone).where(Zone.warehouse_id == warehouse.id, Zone.code == zone_code)
        ).first()
        report.add("zones", created=zone is None)
        if zone is None:
            zone = service.create_zone(
                warehouse.id, ZoneCreate(code=zone_code, name=zone_name, zone_type=zone_type)
            )
        if zone.racks:  # layout already generated: leave it as it is
            existing_bins = db.scalar(
                select(func.count(Bin.id))
                .join(Bin.shelf)
                .join(Shelf.rack)
                .where(Rack.zone_id == zone.id)
            )
            report.skipped["bins"] = report.skipped.get("bins", 0) + (existing_bins or 0)
            continue
        result = service.generate(
            zone.id,
            GenerateLayoutRequest(
                racks=racks,
                shelves_per_rack=shelves,
                bins_per_shelf=bins,
                max_weight_kg=Decimal(kg),
                max_volume_cm3=cm3,
                first_rack_distance_m=Decimal(distance),
                distance_step_m=Decimal("2"),
            ),
        )
        report.created["bins"] = report.created.get("bins", 0) + result.bins_created


# ----------------------------------------------------------------------------- reset
def reset(db: Session) -> None:
    """Delete catalog, warehouse layout and the demo users. Other users are kept."""
    settings = get_settings()
    if settings.app_env not in INSECURE_SECRET_ALLOWED_ENVS:
        raise SeedError(f"--reset is only allowed in development/test (APP_ENV={settings.app_env})")
    db.execute(delete(SupplierProduct))
    db.execute(delete(Product))
    db.execute(update(Category).values(parent_id=None))  # unlink the tree before deleting
    db.execute(delete(Category))
    db.execute(delete(Supplier))
    for model in (Bin, Shelf, Rack, Zone, Warehouse):  # bottom-up (parents are protected)
        db.execute(delete(model))
    demo_emails = [email for email, _, _ in DEMO_USERS]
    for user in db.scalars(select(User).where(User.email.in_(demo_emails))):
        db.delete(user)
    db.commit()


# ------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None, session_factory: SessionFactory = SessionLocal) -> int:
    parser = argparse.ArgumentParser(description="Load demo data into the local database.")
    parser.add_argument(
        "--reset", action="store_true", help="delete demo data first (development only)"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask before --reset")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.app_env not in INSECURE_SECRET_ALLOWED_ENVS:
        print(
            f"Error: demo data (with a shared demo password) is not allowed when "
            f"APP_ENV={settings.app_env}.",
            file=sys.stderr,
        )
        return 1
    try:
        with session_factory() as db:
            if args.reset:
                if not args.yes:
                    answer = input("Delete ALL catalog and warehouse data and demo users? [y/N] ")
                    if answer.strip().lower() not in {"y", "yes"}:
                        print("Cancelled.")
                        return 1
                reset(db)
                print("Demo data removed.")
            report = seed(db)
    except SeedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Demo data loaded:")
    print("\n".join(report.lines()))
    print(f"\nDemo logins: {', '.join(e for e, _, _ in DEMO_USERS)}")
    print(f"Password: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
