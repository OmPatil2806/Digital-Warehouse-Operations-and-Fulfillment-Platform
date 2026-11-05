"""Aggregates all version 1 API routers."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit,
    auth,
    categories,
    cycle_counts,
    health,
    inventory,
    products,
    suppliers,
    users,
    warehouses,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(categories.router)
api_router.include_router(products.router)
api_router.include_router(suppliers.router)
api_router.include_router(warehouses.router)
api_router.include_router(audit.router)
api_router.include_router(inventory.router)
api_router.include_router(cycle_counts.router)
api_router.include_router(alerts.router)
