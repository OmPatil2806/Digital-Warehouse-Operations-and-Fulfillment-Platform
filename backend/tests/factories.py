"""Helpers that create test data."""

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import RoleName, User
from app.repositories.user_repository import UserRepository

if TYPE_CHECKING:
    from app.models.catalog import Category, Product, Supplier
    from app.models.warehouse import Bin

DEFAULT_PASSWORD = "Passw0rd-123"


def create_user(
    db: Session,
    email: str = "user@example.com",
    *,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test User",
    roles: tuple[RoleName, ...] = (RoleName.CUSTOMER,),
    is_active: bool = True,
) -> User:
    """Insert a user with the given roles and commit."""
    repo = UserRepository(db)
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hash_password(password),
        is_active=is_active,
    )
    user.roles = repo.get_roles_by_names(roles)
    repo.add(user)
    db.commit()
    return user


# ------------------------------------------------------------------------- auth helpers
def auth_headers(user: User) -> dict[str, str]:
    """Authorization header with a fresh access token for `user`."""
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def user_with_role(db: Session, role: RoleName) -> User:
    return create_user(db, f"{role.value}@example.com", roles=(role,))


# ---------------------------------------------------------------------- catalog helpers
def create_category(db: Session, name: str = "Electronics", **extra: object) -> "Category":
    from app.models.catalog import Category

    category = Category(name=name, **extra)
    db.add(category)
    db.commit()
    return category


def create_supplier(db: Session, code: str = "SUP-001", **extra: object) -> "Supplier":
    from app.models.catalog import Supplier

    supplier = Supplier(code=code, name=extra.pop("name", f"Supplier {code}"), **extra)
    db.add(supplier)
    db.commit()
    return supplier


def create_product(
    db: Session, category: "Category", sku: str = "LAP-001", **overrides: object
) -> "Product":
    from decimal import Decimal

    from app.models.catalog import Product

    values: dict[str, object] = {
        "sku": sku,
        "name": f"Product {sku}",
        "category_id": category.id,
        "unit_price": Decimal("100.00"),
        "unit_cost": Decimal("60.00"),
        "weight_kg": Decimal("1.000"),
        "length_cm": Decimal("10.0"),
        "width_cm": Decimal("10.0"),
        "height_cm": Decimal("10.0"),
    }
    values.update(overrides)
    product = Product(**values)
    db.add(product)
    db.commit()
    return product


# -------------------------------------------------------------------- warehouse helpers
def create_bin(
    db: Session,
    location: str = "WH01-ZA-R01-S01-B01",
    *,
    max_weight_kg: str = "100.000",
    max_volume_cm3: int = 1_000_000,
) -> "Bin":
    """Insert a bin, and any missing parents, from a location code like WH01-ZA-R01-S01-B01."""
    from decimal import Decimal

    from sqlalchemy import func, select

    from app.models.warehouse import Bin, Rack, Shelf, Warehouse, Zone

    wh_code, zone_code, rack_code, shelf_code, bin_code = location.split("-")

    def get_or_add(model: type, keys: dict[str, object], **extra: object) -> object:
        found = db.scalar(select(model).filter_by(**keys))
        if found is None:
            found = model(**keys, **extra)
            db.add(found)
            db.flush()
        return found

    warehouse = get_or_add(Warehouse, {"code": wh_code}, name=f"Warehouse {wh_code}")
    zone = get_or_add(
        Zone, {"warehouse_id": warehouse.id, "code": zone_code}, name=zone_code, zone_type="picking"
    )
    rack = get_or_add(Rack, {"zone_id": zone.id, "code": rack_code})
    next_level = (db.scalar(select(func.max(Shelf.level)).filter_by(rack_id=rack.id)) or 0) + 1
    shelf = get_or_add(Shelf, {"rack_id": rack.id, "code": shelf_code}, level=next_level)
    bin_ = Bin(
        shelf_id=shelf.id,
        code=bin_code,
        location_code=location,
        max_weight_kg=Decimal(max_weight_kg),
        max_volume_cm3=max_volume_cm3,
    )
    db.add(bin_)
    db.commit()
    return bin_
