"""Database access for categories, suppliers, products and supplier-product links.

Repositories only read and write rows; they never commit and contain no business rules.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.models.catalog import Category, Product, Supplier, SupplierProduct


def _like(value: str) -> str:
    """Case-insensitive 'contains' pattern with LIKE wildcards escaped."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _paginate(db: Session, query: Select, *, offset: int, limit: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    items = list(db.scalars(query.offset(offset).limit(limit)).unique())
    return items, total


def _order_by(sort: str, columns: dict[str, ColumnElement]) -> list[ColumnElement]:
    """'name' -> ascending, '-name' -> descending; id breaks ties for stable paging."""
    descending = sort.startswith("-")
    column = columns[sort.lstrip("-")]
    return [column.desc() if descending else column.asc(), columns["id"].asc()]


# ------------------------------------------------------------------------ categories
class CategoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, category_id: int) -> Category | None:
        return self.db.get(Category, category_id)

    def name_exists(self, name: str, *, exclude_id: int | None = None) -> bool:
        query = select(Category.id).where(func.lower(Category.name) == name.lower())
        if exclude_id is not None:
            query = query.where(Category.id != exclude_id)
        return self.db.scalars(query).first() is not None

    def list_with_counts(
        self,
        *,
        q: str | None,
        is_active: bool | None,
        parent_id: int | None,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Category, int]], int]:
        """Categories plus the number of active products in each."""
        product_count = (
            select(func.count(Product.id))
            .where(Product.category_id == Category.id, Product.is_active.is_(True))
            .correlate(Category)
            .scalar_subquery()
        )
        query = select(Category, product_count).order_by(Category.name, Category.id)
        if q:
            query = query.where(Category.name.ilike(_like(q), escape="\\"))
        if is_active is not None:
            query = query.where(Category.is_active.is_(is_active))
        if parent_id is not None:
            query = query.where(Category.parent_id == parent_id)
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        rows = self.db.execute(query.offset(offset).limit(limit)).all()
        return [(row[0], row[1]) for row in rows], total or 0

    def all_parent_links(self) -> dict[int, int | None]:
        """{category_id: parent_id} for every category (used for tree checks)."""
        return {
            child: parent
            for child, parent in self.db.execute(select(Category.id, Category.parent_id))
        }

    def count_active_products(self, category_id: int) -> int:
        return (
            self.db.scalar(
                select(func.count(Product.id)).where(
                    Product.category_id == category_id, Product.is_active.is_(True)
                )
            )
            or 0
        )

    def count_active_children(self, category_id: int) -> int:
        return (
            self.db.scalar(
                select(func.count(Category.id)).where(
                    Category.parent_id == category_id, Category.is_active.is_(True)
                )
            )
            or 0
        )

    def add(self, category: Category) -> Category:
        self.db.add(category)
        self.db.flush()
        return category


# ------------------------------------------------------------------------- suppliers
class SupplierRepository:
    SORT_COLUMNS = {
        "id": Supplier.id,
        "code": Supplier.code,
        "name": Supplier.name,
        "lead_time_days": Supplier.lead_time_days,
        "reliability_score": Supplier.reliability_score,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, supplier_id: int) -> Supplier | None:
        return self.db.get(Supplier, supplier_id)

    def code_exists(self, code: str, *, exclude_id: int | None = None) -> bool:
        query = select(Supplier.id).where(Supplier.code == code)
        if exclude_id is not None:
            query = query.where(Supplier.id != exclude_id)
        return self.db.scalars(query).first() is not None

    def search(
        self, *, q: str | None, is_active: bool | None, sort: str, offset: int, limit: int
    ) -> tuple[list[Supplier], int]:
        query = select(Supplier).order_by(*_order_by(sort, self.SORT_COLUMNS))
        if q:
            pattern = _like(q)
            query = query.where(
                or_(
                    Supplier.code.ilike(pattern, escape="\\"),
                    Supplier.name.ilike(pattern, escape="\\"),
                    Supplier.email.ilike(pattern, escape="\\"),
                    Supplier.country.ilike(pattern, escape="\\"),
                )
            )
        if is_active is not None:
            query = query.where(Supplier.is_active.is_(is_active))
        return _paginate(self.db, query, offset=offset, limit=limit)

    def add(self, supplier: Supplier) -> Supplier:
        self.db.add(supplier)
        self.db.flush()
        return supplier


# -------------------------------------------------------------------------- products
@dataclass(frozen=True)
class ProductFilters:
    q: str | None = None
    category_ids: Sequence[int] | None = None  # already expanded with sub-categories
    supplier_id: int | None = None
    is_active: bool | None = None


class ProductRepository:
    SORT_COLUMNS = {
        "id": Product.id,
        "sku": Product.sku,
        "name": Product.name,
        "unit_price": Product.unit_price,
        "created_at": Product.created_at,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def _with_relations(self) -> Select:
        return select(Product).options(
            joinedload(Product.category), joinedload(Product.default_supplier)
        )

    def get(self, product_id: int) -> Product | None:
        return self.db.scalars(self._with_relations().where(Product.id == product_id)).first()

    def sku_exists(self, sku: str, *, exclude_id: int | None = None) -> bool:
        query = select(Product.id).where(Product.sku == sku)
        if exclude_id is not None:
            query = query.where(Product.id != exclude_id)
        return self.db.scalars(query).first() is not None

    def barcode_exists(self, barcode: str, *, exclude_id: int | None = None) -> bool:
        query = select(Product.id).where(Product.barcode == barcode)
        if exclude_id is not None:
            query = query.where(Product.id != exclude_id)
        return self.db.scalars(query).first() is not None

    def search(
        self, filters: ProductFilters, *, sort: str, offset: int, limit: int
    ) -> tuple[list[Product], int]:
        query = self._with_relations().order_by(*_order_by(sort, self.SORT_COLUMNS))
        if filters.q:
            pattern = _like(filters.q)
            query = query.where(
                or_(
                    Product.sku.ilike(pattern, escape="\\"),
                    Product.name.ilike(pattern, escape="\\"),
                    Product.brand.ilike(pattern, escape="\\"),
                    Product.barcode.ilike(pattern, escape="\\"),
                )
            )
        if filters.category_ids is not None:
            query = query.where(Product.category_id.in_(filters.category_ids))
        if filters.supplier_id is not None:
            linked = select(SupplierProduct.product_id).where(
                SupplierProduct.supplier_id == filters.supplier_id
            )
            query = query.where(
                or_(Product.default_supplier_id == filters.supplier_id, Product.id.in_(linked))
            )
        if filters.is_active is not None:
            query = query.where(Product.is_active.is_(filters.is_active))
        return _paginate(self.db, query, offset=offset, limit=limit)

    def add(self, product: Product) -> Product:
        self.db.add(product)
        self.db.flush()
        return product


# ---------------------------------------------------------------- supplier products
class SupplierProductRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _with_relations(self) -> Select:
        return select(SupplierProduct).options(
            joinedload(SupplierProduct.supplier), joinedload(SupplierProduct.product)
        )

    def get(self, supplier_id: int, product_id: int) -> SupplierProduct | None:
        return self.db.scalars(
            self._with_relations().where(
                SupplierProduct.supplier_id == supplier_id,
                SupplierProduct.product_id == product_id,
            )
        ).first()

    def for_supplier(self, supplier_id: int) -> list[SupplierProduct]:
        query = (
            self._with_relations()
            .join(SupplierProduct.product)
            .where(SupplierProduct.supplier_id == supplier_id)
            .order_by(Product.sku)
        )
        return list(self.db.scalars(query).unique())

    def for_product(self, product_id: int) -> list[SupplierProduct]:
        query = (
            self._with_relations()
            .join(SupplierProduct.supplier)
            .where(SupplierProduct.product_id == product_id)
            .order_by(SupplierProduct.is_preferred.desc(), Supplier.code)
        )
        return list(self.db.scalars(query).unique())

    def clear_preferred(self, product_id: int, *, except_id: int | None = None) -> None:
        """A product has at most one preferred supplier."""
        statement = update(SupplierProduct).where(
            SupplierProduct.product_id == product_id, SupplierProduct.is_preferred.is_(True)
        )
        if except_id is not None:
            statement = statement.where(SupplierProduct.id != except_id)
        self.db.execute(
            statement.values(is_preferred=False).execution_options(synchronize_session="fetch")
        )

    def add(self, link: SupplierProduct) -> SupplierProduct:
        self.db.add(link)
        self.db.flush()
        return link

    def delete(self, link: SupplierProduct) -> None:
        self.db.delete(link)
        self.db.flush()
