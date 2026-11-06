"""Alerts: raised and resolved automatically from the stock, handled by people.

Rules (evaluated after every stock change, in the same transaction):

- LOW_STOCK (per product): available units in active bins < the product's `min_stock`.
  Severity is critical when nothing is available, warning otherwise. Products with
  min_stock 0 and archived products never raise it.
- OVER_CAPACITY (per bin): the weight or volume of everything in the bin is above its
  limits (e.g. after a cycle count found more units, or the bin limits were lowered).

There is at most one unresolved alert per cause (`dedup_key`, enforced by a partial
unique index). While the cause lasts, the alert is kept up to date; when the cause is
gone it is resolved automatically (resolved_by = NULL). A person can acknowledge an
alert ("I'm on it") or resolve it by hand; if the cause is still there, the next stock
change raises a new alert.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError
from app.models.audit import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.catalog import Product
from app.models.inventory import Inventory
from app.models.user import User
from app.models.warehouse import Bin

UNRESOLVED = (AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value)


class AlertNotFoundError(NotFoundError):
    message = "Alert not found"


def low_stock_key(product_id: int) -> str:
    return f"{AlertType.LOW_STOCK.value}:product:{product_id}"


def over_capacity_key(bin_id: int) -> str:
    return f"{AlertType.OVER_CAPACITY.value}:bin:{bin_id}"


def delay_key(order_id: int) -> str:
    return f"{AlertType.DELAY_RISK.value}:order:{order_id}"


class AlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------- evaluate
    def evaluate(self, product_ids: Iterable[int] = (), bin_ids: Iterable[int] = ()) -> None:
        """Raise, update or resolve alerts for these products and bins (no commit)."""
        self.db.flush()  # the rules read the stock from the database
        for product_id in sorted(set(product_ids)):
            self.evaluate_product(product_id)
        for bin_id in sorted(set(bin_ids)):
            self.evaluate_bin(bin_id)

    def evaluate_product(self, product_id: int) -> Alert | None:
        product = self.db.get(Product, product_id)
        if product is None:
            return None
        available = self.available_quantity(product_id)
        low = product.is_active and product.min_stock > 0 and available < product.min_stock
        if not low:
            self._resolve_automatically(low_stock_key(product_id))
            return None
        return self._raise(
            AlertType.LOW_STOCK,
            low_stock_key(product_id),
            severity=AlertSeverity.CRITICAL if available == 0 else AlertSeverity.WARNING,
            title=f"Low stock: {product.sku}",
            message=(
                f"{product.name}: {available} available, minimum stock is {product.min_stock}."
            ),
            product_id=product.id,
        )

    def evaluate_bin(self, bin_id: int) -> Alert | None:
        bin_ = self.db.get(Bin, bin_id)
        if bin_ is None:
            return None
        weight, volume = self._bin_load(bin_id)
        problems = []
        if weight > bin_.max_weight_kg:
            problems.append(f"weight {weight} kg of max {bin_.max_weight_kg} kg")
        if volume > bin_.max_volume_cm3:
            problems.append(f"volume {volume} cm³ of max {bin_.max_volume_cm3} cm³")
        if not problems:
            self._resolve_automatically(over_capacity_key(bin_id))
            return None
        return self._raise(
            AlertType.OVER_CAPACITY,
            over_capacity_key(bin_id),
            severity=AlertSeverity.WARNING,
            title=f"Bin over capacity: {bin_.location_code}",
            message="Contents exceed the bin limits: " + "; ".join(problems) + ".",
            bin_id=bin_.id,
            warehouse_id=bin_.shelf.rack.zone.warehouse_id,
        )

    def available_quantity(self, product_id: int) -> int:
        """Available units of a product over all active bins."""
        available = (
            Inventory.quantity_on_hand - Inventory.quantity_reserved - Inventory.quantity_damaged
        )
        total = self.db.scalar(
            select(func.coalesce(func.sum(available), 0))
            .join(Bin, Inventory.bin_id == Bin.id)
            .where(Inventory.product_id == product_id, Bin.is_active.is_(True))
        )
        return int(total or 0)

    # -------------------------------------------------------- other modules
    def raise_alert(self, alert_type: AlertType, dedup_key: str, **values: object) -> Alert:
        """Raise (or update) the unresolved alert for this cause (no commit)."""
        return self._raise(alert_type, dedup_key, **values)

    def resolve_cause(self, dedup_key: str) -> None:
        """The cause is gone: resolve its unresolved alert, if any (no commit)."""
        self._resolve_automatically(dedup_key)

    # --------------------------------------------------------- people actions
    def get(self, alert_id: int) -> Alert:
        alert = self.db.get(Alert, alert_id)
        if alert is None:
            raise AlertNotFoundError()
        return alert

    def acknowledge(self, alert_id: int, *, user: User) -> Alert:
        alert = self.get(alert_id)
        if alert.status != AlertStatus.OPEN:
            raise ConflictError(f"This alert is already {alert.status}")
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by = user
        alert.acknowledged_at = datetime.now(UTC)
        self.db.commit()
        return alert

    def resolve(self, alert_id: int, *, user: User) -> Alert:
        alert = self.get(alert_id)
        if alert.status == AlertStatus.RESOLVED:
            raise ConflictError("This alert is already resolved")
        alert.status = AlertStatus.RESOLVED
        alert.resolved_by = user
        alert.resolved_at = datetime.now(UTC)
        self.db.commit()
        return alert

    def search(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        unresolved: bool = False,
        alert_type: str | None = None,
        product_id: int | None = None,
        bin_id: int | None = None,
    ) -> tuple[Sequence[Alert], int]:
        """Newest first; critical before warning before info inside the same moment."""
        query: Select = select(Alert)
        if unresolved:
            query = query.where(Alert.status.in_(UNRESOLVED))
        if status is not None:
            query = query.where(Alert.status == status)
        if alert_type is not None:
            query = query.where(Alert.alert_type == alert_type)
        if product_id is not None:
            query = query.where(Alert.product_id == product_id)
        if bin_id is not None:
            query = query.where(Alert.bin_id == bin_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self.db.scalars(
            query.order_by(Alert.created_at.desc(), Alert.id.desc()).offset(offset).limit(limit)
        ).all()
        return items, total

    def count_unresolved(self) -> int:
        return (
            self.db.scalar(
                select(func.count()).select_from(Alert).where(Alert.status.in_(UNRESOLVED))
            )
            or 0
        )

    # --------------------------------------------------------------- helpers
    def _unresolved(self, dedup_key: str) -> Alert | None:
        return self.db.scalar(
            select(Alert).where(Alert.dedup_key == dedup_key, Alert.status.in_(UNRESOLVED))
        )

    def _raise(self, alert_type: AlertType, dedup_key: str, **values: object) -> Alert:
        alert = self._unresolved(dedup_key)
        if alert is None:
            alert = Alert(alert_type=alert_type, dedup_key=dedup_key, status=AlertStatus.OPEN)
            self.db.add(alert)
        for key, value in values.items():  # keep the text and severity up to date
            setattr(alert, key, value)
        self.db.flush()
        return alert

    def _resolve_automatically(self, dedup_key: str) -> None:
        alert = self._unresolved(dedup_key)
        if alert is not None:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.now(UTC)
            alert.resolved_by = None  # the system

    def _bin_load(self, bin_id: int) -> tuple[Decimal, Decimal]:
        rows = self.db.scalars(
            select(Inventory).where(Inventory.bin_id == bin_id, Inventory.quantity_on_hand > 0)
        ).all()
        weight = sum((r.product.weight_kg * r.quantity_on_hand for r in rows), Decimal("0"))
        volume = sum((r.product.volume_cm3 * r.quantity_on_hand for r in rows), Decimal("0"))
        return weight, volume
