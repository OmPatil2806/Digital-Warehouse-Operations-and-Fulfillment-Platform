"""Business rules for categories, suppliers, products and supplier-product links.

Rules (beyond field validation in the schemas):
- SKUs, barcodes, supplier codes and category names are unique (409 Conflict).
- Referenced records must exist and be active (422 Unprocessable).
- Categories form a tree: no category can become its own ancestor.
- Nothing is deleted; records are archived with is_active=False. A category can only be
  archived when it has no active products and no active sub-categories.
- A product has at most one preferred supplier.
"""

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Category, Product, Supplier, SupplierProduct
from app.repositories.catalog_repository import (
    CategoryRepository,
    ProductFilters,
    ProductRepository,
    SupplierProductRepository,
    SupplierRepository,
)
from app.schemas.catalog import (
    CategoryCreate,
    CategoryUpdate,
    ProductCreate,
    ProductUpdate,
    SupplierCreate,
    SupplierProductCreate,
    SupplierProductUpdate,
    SupplierUpdate,
)
from app.services.alert_service import AlertService

logger = get_logger(__name__)


def _commit(db: Session, conflict_message: str) -> None:
    """Commit; a unique-constraint race (two identical requests at once) becomes a 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(conflict_message) from exc


def _apply(obj: object, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        setattr(obj, field, value)


# ------------------------------------------------------------------------ categories
class CategoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.categories = CategoryRepository(db)

    def get(self, category_id: int) -> Category:
        category = self.categories.get(category_id)
        if category is None:
            raise NotFoundError("Category not found")
        return category

    def search(self, **filters: Any) -> tuple[list[tuple[Category, int]], int]:
        return self.categories.list_with_counts(**filters)

    def descendant_ids(self, category_id: int) -> list[int]:
        """The category itself plus all categories below it."""
        children: dict[int | None, list[int]] = {}
        for child, parent in self.categories.all_parent_links().items():
            children.setdefault(parent, []).append(child)
        result, stack = [], [category_id]
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(children.get(current, []))
        return result

    def create(self, data: CategoryCreate) -> Category:
        if self.categories.name_exists(data.name):
            raise ConflictError("A category with this name already exists")
        if data.parent_id is not None:
            self._require_active_parent(data.parent_id)
        category = self.categories.add(Category(**data.model_dump()))
        _commit(self.db, "A category with this name already exists")
        return category

    def update(self, category_id: int, data: CategoryUpdate) -> Category:
        category = self.get(category_id)
        changes = data.model_dump(exclude_unset=True)

        if changes.get("name") is not None and self.categories.name_exists(
            changes["name"], exclude_id=category.id
        ):
            raise ConflictError("A category with this name already exists")
        if "parent_id" in changes and changes["parent_id"] is not None:
            parent_id = changes["parent_id"]
            if parent_id in self.descendant_ids(category.id):
                raise UnprocessableError(
                    "A category cannot be placed inside itself or a sub-category"
                )
            self._require_active_parent(parent_id)
        if changes.get("is_active") is False and category.is_active:
            self._ensure_can_archive(category)
        if changes.get("is_active") is True and category.parent and not category.parent.is_active:
            raise UnprocessableError("Restore the parent category first")

        nullable = {"parent_id", "description"}
        _apply(category, {k: v for k, v in changes.items() if v is not None or k in nullable})
        _commit(self.db, "A category with this name already exists")
        return category

    def _require_active_parent(self, parent_id: int) -> None:
        parent = self.categories.get(parent_id)
        if parent is None:
            raise UnprocessableError("Parent category not found")
        if not parent.is_active:
            raise UnprocessableError("Parent category is archived")

    def _ensure_can_archive(self, category: Category) -> None:
        if self.categories.count_active_products(category.id):
            raise ConflictError("Archive or move the active products in this category first")
        if self.categories.count_active_children(category.id):
            raise ConflictError("Archive the active sub-categories first")


# ------------------------------------------------------------------------- suppliers
class SupplierService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.suppliers = SupplierRepository(db)

    def get(self, supplier_id: int) -> Supplier:
        supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier not found")
        return supplier

    def search(self, **filters: Any) -> tuple[list[Supplier], int]:
        return self.suppliers.search(**filters)

    def create(self, data: SupplierCreate) -> Supplier:
        if self.suppliers.code_exists(data.code):
            raise ConflictError("A supplier with this code already exists")
        supplier = self.suppliers.add(Supplier(**data.model_dump()))
        _commit(self.db, "A supplier with this code already exists")
        logger.info("Created supplier %s", supplier.code)
        return supplier

    def update(self, supplier_id: int, data: SupplierUpdate) -> Supplier:
        supplier = self.get(supplier_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("code") is not None and self.suppliers.code_exists(
            changes["code"], exclude_id=supplier.id
        ):
            raise ConflictError("A supplier with this code already exists")
        # Optional contact fields may be cleared with null; required ones may not.
        nullable = {"contact_name", "email", "phone", "address", "country"}
        _apply(supplier, {k: v for k, v in changes.items() if v is not None or k in nullable})
        _commit(self.db, "A supplier with this code already exists")
        return supplier


# -------------------------------------------------------------------------- products
class ProductService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.products = ProductRepository(db)
        self.categories = CategoryService(db)
        self.suppliers = SupplierRepository(db)

    def get(self, product_id: int, *, active_only: bool = False) -> Product:
        product = self.products.get(product_id)
        if product is None or (active_only and not product.is_active):
            raise NotFoundError("Product not found")
        return product

    def search(
        self,
        *,
        q: str | None,
        category_id: int | None,
        supplier_id: int | None,
        is_active: bool | None,
        sort: str,
        offset: int,
        limit: int,
    ) -> tuple[list[Product], int]:
        category_ids = None
        if category_id is not None:
            self.categories.get(category_id)  # 404 if missing
            category_ids = self.categories.descendant_ids(category_id)
        filters = ProductFilters(
            q=q, category_ids=category_ids, supplier_id=supplier_id, is_active=is_active
        )
        return self.products.search(filters, sort=sort, offset=offset, limit=limit)

    def create(self, data: ProductCreate) -> Product:
        self._check_unique(sku=data.sku, barcode=data.barcode)
        self._require_category(data.category_id)
        if data.default_supplier_id is not None:
            self._require_supplier(data.default_supplier_id)
        product = self.products.add(Product(**data.model_dump()))
        _commit(self.db, "A product with this SKU or barcode already exists")
        logger.info("Created product %s", product.sku)
        return self.get(product.id)

    def update(self, product_id: int, data: ProductUpdate) -> Product:
        product = self.get(product_id)
        changes = data.model_dump(exclude_unset=True)
        nullable = {"description", "brand", "barcode", "max_stock", "default_supplier_id"}
        changes = {k: v for k, v in changes.items() if v is not None or k in nullable}

        self._check_unique(
            sku=changes.get("sku"),
            barcode=changes.get("barcode"),
            exclude_id=product.id,
        )
        if "category_id" in changes:
            self._require_category(changes["category_id"])
        if changes.get("default_supplier_id") is not None:
            self._require_supplier(changes["default_supplier_id"])
        if changes.get("is_active") is True and not product.category.is_active:
            raise UnprocessableError("Restore the product's category first")

        min_stock = changes.get("min_stock", product.min_stock)
        max_stock = changes.get("max_stock", product.max_stock)
        if max_stock is not None and max_stock < min_stock:
            raise UnprocessableError("max_stock must be greater than or equal to min_stock")

        _apply(product, changes)
        if {"min_stock", "is_active"} & changes.keys():
            # A new minimum (or archiving) can raise or resolve a low-stock alert.
            AlertService(self.db).evaluate(product_ids=[product.id])
        _commit(self.db, "A product with this SKU or barcode already exists")
        self.db.expire(product)
        return self.get(product.id)

    def _check_unique(
        self, *, sku: str | None, barcode: str | None, exclude_id: int | None = None
    ) -> None:
        if sku is not None and self.products.sku_exists(sku, exclude_id=exclude_id):
            raise ConflictError("A product with this SKU already exists")
        if barcode is not None and self.products.barcode_exists(barcode, exclude_id=exclude_id):
            raise ConflictError("A product with this barcode already exists")

    def _require_category(self, category_id: int) -> None:
        category = self.categories.categories.get(category_id)
        if category is None:
            raise UnprocessableError("Category not found")
        if not category.is_active:
            raise UnprocessableError("Category is archived")

    def _require_supplier(self, supplier_id: int) -> None:
        supplier = self.suppliers.get(supplier_id)
        if supplier is None:
            raise UnprocessableError("Default supplier not found")
        if not supplier.is_active:
            raise UnprocessableError("Default supplier is archived")


# ---------------------------------------------------------------- supplier products
class SupplierProductService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.links = SupplierProductRepository(db)
        self.suppliers = SupplierService(db)
        self.products = ProductRepository(db)

    def for_supplier(self, supplier_id: int) -> list[SupplierProduct]:
        self.suppliers.get(supplier_id)
        return self.links.for_supplier(supplier_id)

    def for_product(self, product_id: int) -> list[SupplierProduct]:
        if self.products.get(product_id) is None:
            raise NotFoundError("Product not found")
        return self.links.for_product(product_id)

    def add(self, supplier_id: int, data: SupplierProductCreate) -> SupplierProduct:
        supplier = self.suppliers.get(supplier_id)
        if not supplier.is_active:
            raise UnprocessableError("Supplier is archived")
        if self.products.get(data.product_id) is None:
            raise UnprocessableError("Product not found")
        if self.links.get(supplier_id, data.product_id) is not None:
            raise ConflictError("This supplier already offers this product")
        if data.is_preferred:
            self.links.clear_preferred(data.product_id)
        self.links.add(SupplierProduct(supplier_id=supplier_id, **data.model_dump()))
        _commit(self.db, "This supplier already offers this product")
        return self._get_link(supplier_id, data.product_id)

    def update(
        self, supplier_id: int, product_id: int, data: SupplierProductUpdate
    ) -> SupplierProduct:
        link = self._get_link(supplier_id, product_id)
        changes = data.model_dump(exclude_unset=True)
        changes = {
            k: v
            for k, v in changes.items()
            if v is not None or k in {"supplier_sku", "lead_time_days"}
        }
        if changes.get("is_preferred"):
            self.links.clear_preferred(product_id, except_id=link.id)
        _apply(link, changes)
        _commit(self.db, "This supplier already offers this product")
        self.db.expire(link)
        return self._get_link(supplier_id, product_id)

    def remove(self, supplier_id: int, product_id: int) -> None:
        self.links.delete(self._get_link(supplier_id, product_id))
        self.db.commit()

    def _get_link(self, supplier_id: int, product_id: int) -> SupplierProduct:
        link = self.links.get(supplier_id, product_id)
        if link is None:
            raise NotFoundError("This supplier does not offer this product")
        return link
