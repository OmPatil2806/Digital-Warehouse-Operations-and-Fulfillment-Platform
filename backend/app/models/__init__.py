"""ORM models.

Every model module must be imported here so that `Base.metadata` knows all tables
(Alembic autogenerate and the test database rely on this).
"""

from app.models.audit import Alert, AlertSeverity, AlertStatus, AlertType, AuditAction, AuditLog
from app.models.catalog import Category, Product, Supplier, SupplierProduct
from app.models.fulfillment import PackingTask, PackingTaskStatus, PickingTask, PickingTaskStatus
from app.models.inventory import (
    AdjustmentKind,
    CycleCount,
    CycleCountLine,
    CycleCountStatus,
    DocumentStatus,
    Inventory,
    InventoryMovement,
    MovementType,
    ReferenceType,
    ReservationStatus,
    StockAdjustment,
    StockReservation,
    StockTransfer,
)
from app.models.order import (
    Customer,
    CustomerType,
    Order,
    OrderItem,
    OrderPriority,
    OrderStatus,
    OrderStatusHistory,
    Return,
    ReturnCondition,
    ReturnItem,
    ReturnStatus,
)
from app.models.shipment import (
    Carrier,
    Shipment,
    ShipmentEvent,
    ShipmentEventType,
    ShipmentStatus,
)
from app.models.user import ROLE_DESCRIPTIONS, RefreshToken, Role, RoleName, User, user_roles
from app.models.warehouse import Bin, Rack, Shelf, Warehouse, Zone, ZoneType, build_location_code

__all__ = [
    "ROLE_DESCRIPTIONS",
    "AdjustmentKind",
    "Alert",
    "AlertSeverity",
    "AlertStatus",
    "AlertType",
    "AuditAction",
    "AuditLog",
    "Bin",
    "Carrier",
    "Category",
    "Customer",
    "CustomerType",
    "CycleCount",
    "CycleCountLine",
    "CycleCountStatus",
    "DocumentStatus",
    "Inventory",
    "InventoryMovement",
    "MovementType",
    "Order",
    "OrderItem",
    "OrderPriority",
    "OrderStatus",
    "OrderStatusHistory",
    "PackingTask",
    "PackingTaskStatus",
    "PickingTask",
    "PickingTaskStatus",
    "Product",
    "Rack",
    "ReferenceType",
    "RefreshToken",
    "ReservationStatus",
    "Return",
    "ReturnCondition",
    "ReturnItem",
    "ReturnStatus",
    "Role",
    "RoleName",
    "Shelf",
    "Shipment",
    "ShipmentEvent",
    "ShipmentEventType",
    "ShipmentStatus",
    "StockAdjustment",
    "StockReservation",
    "StockTransfer",
    "Supplier",
    "SupplierProduct",
    "User",
    "Warehouse",
    "Zone",
    "ZoneType",
    "build_location_code",
    "user_roles",
]

# Record changes of users, catalog and layout in the audit log (see audit_tracking.py).
from app.services.audit_tracking import install_audit_tracking  # noqa: E402

install_audit_tracking()
