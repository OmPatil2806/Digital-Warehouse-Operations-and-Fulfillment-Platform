"""Helpers that create test data."""

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import RoleName, User
from app.repositories.user_repository import UserRepository

if TYPE_CHECKING:
    from app.models.catalog import Category, Product, Supplier

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
