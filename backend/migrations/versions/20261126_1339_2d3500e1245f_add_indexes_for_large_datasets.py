"""add indexes for large datasets

Found by the Phase 10 speed check (scripts/benchmark_api.py) on the full dataset
(500,000 orders, 3.3 million stock movements): lists sorted newest first and the
dashboards' date filters read whole tables without these indexes.

    inventory_movements (created_at, id)   stock history, newest first: 6 s -> 20 ms
    orders (created_at, id)                order list, newest first: 0.7 s -> 15 ms
    orders (shipped_at), (delivered_at)    fulfillment dashboard
    shipments (shipped_at, id)             shipment list, newest first
    shipments (delivered_at)               on-time delivery counts
    picking_tasks (completed_at)           fulfillment dashboard

No ANALYZE: SQLite's statistics only know the average rows per value, and the status
columns are very lopsided (a handful of open tasks among 1.37 million done ones), so with
statistics the planner stopped using the status indexes (open picking tasks: 10 ms ->
1.1 s). Without them it chooses well.

Revision ID: 2d3500e1245f
Revises: 7884bc83d50d
Create Date: 2026-11-26 13:39:23.028147

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d3500e1245f"
down_revision: str | Sequence[str] | None = "7884bc83d50d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = [
    ("ix_inventory_movements_created_at", "inventory_movements", ["created_at", "id"]),
    ("ix_orders_created_at", "orders", ["created_at", "id"]),
    ("ix_orders_shipped_at", "orders", ["shipped_at"]),
    ("ix_orders_delivered_at", "orders", ["delivered_at"]),
    ("ix_shipments_shipped_at", "shipments", ["shipped_at", "id"]),
    ("ix_shipments_delivered_at", "shipments", ["delivered_at"]),
    ("ix_picking_tasks_completed_at", "picking_tasks", ["completed_at"]),
]


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
