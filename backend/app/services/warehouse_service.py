"""Business rules for the warehouse layout (Warehouse > Zone > Rack > Shelf > Bin).

- Codes are unique within their parent and cannot change after creation.
- Every bin gets its full location code (WH01-ZA-R05-S03-B08) automatically.
- Archiving a record also archives everything below it. Restoring works one level at a
  time and requires the parent to be active.
- Bulk generation creates racks/shelves/bins in ONE transaction: all or nothing.
"""

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.logging import get_logger
from app.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.catalog import Product
from app.models.warehouse import Bin, Rack, Shelf, Warehouse, Zone, build_location_code
from app.schemas.warehouse import (
    BinCreate,
    BinUpdate,
    CapacityTotals,
    GenerateLayoutRequest,
    GenerateLayoutResponse,
    RackCreate,
    RackUpdate,
    ShelfCreate,
    ShelfUpdate,
    WarehouseCreate,
    WarehouseUpdate,
    ZoneCreate,
    ZoneUpdate,
)
from app.services.capacity import FitCheck, product_fits_bin

logger = get_logger(__name__)

Node = Warehouse | Zone | Rack | Shelf | Bin


def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(conflict_message) from exc


def _children(node: Node) -> Sequence[Node]:
    if isinstance(node, Warehouse):
        return node.zones
    if isinstance(node, Zone):
        return node.racks
    if isinstance(node, Rack):
        return node.shelves
    if isinstance(node, Shelf):
        return node.bins
    return []


def _parent(node: Node) -> Node | None:
    if isinstance(node, Zone):
        return node.warehouse
    if isinstance(node, Rack):
        return node.zone
    if isinstance(node, Shelf):
        return node.rack
    if isinstance(node, Bin):
        return node.shelf
    return None


class WarehouseService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ lookups
    def _get(self, model: type[Node], node_id: int, label: str) -> Node:
        node = self.db.get(model, node_id)
        if node is None:
            raise NotFoundError(f"{label} not found")
        return node

    def get_warehouse(self, warehouse_id: int) -> Warehouse:
        return self._get(Warehouse, warehouse_id, "Warehouse")

    def get_zone(self, zone_id: int) -> Zone:
        return self._get(Zone, zone_id, "Zone")

    def get_rack(self, rack_id: int) -> Rack:
        return self._get(Rack, rack_id, "Rack")

    def get_shelf(self, shelf_id: int) -> Shelf:
        return self._get(Shelf, shelf_id, "Shelf")

    def get_bin(self, bin_id: int) -> Bin:
        return self._get(Bin, bin_id, "Bin")

    def get_bin_by_code(self, location_code: str) -> Bin:
        bin_ = self.db.scalars(
            select(Bin)
            .options(joinedload(Bin.shelf).joinedload(Shelf.rack).joinedload(Rack.zone))
            .where(Bin.location_code == location_code.strip().upper())
        ).first()
        if bin_ is None:
            raise NotFoundError("No bin with this location code")
        return bin_

    def list_warehouses(self, *, is_active: bool | None) -> list[Warehouse]:
        query = select(Warehouse).order_by(Warehouse.code)
        if is_active is not None:
            query = query.where(Warehouse.is_active.is_(is_active))
        return list(self.db.scalars(query))

    def search_bins(
        self,
        *,
        warehouse_id: int | None,
        zone_id: int | None,
        q: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Bin], int]:
        query = (
            select(Bin).join(Bin.shelf).join(Shelf.rack).join(Rack.zone).order_by(Bin.location_code)
        )
        if warehouse_id is not None:
            query = query.where(Zone.warehouse_id == warehouse_id)
        if zone_id is not None:
            query = query.where(Rack.zone_id == zone_id)
        if q:
            query = query.where(Bin.location_code.contains(q.strip().upper(), autoescape=True))
        if is_active is not None:
            query = query.where(Bin.is_active.is_(is_active))
        total = self.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        return list(self.db.scalars(query.offset(offset).limit(limit))), total or 0

    # ------------------------------------------------------------------- layout
    def layout(self, warehouse_id: int, *, include_inactive: bool) -> dict[str, Any]:
        """The whole tree of a warehouse with capacity totals per zone and overall."""
        warehouse = self.db.scalars(
            select(Warehouse)
            .options(
                selectinload(Warehouse.zones)
                .selectinload(Zone.racks)
                .selectinload(Rack.shelves)
                .selectinload(Shelf.bins)
            )
            .where(Warehouse.id == warehouse_id)
        ).first()
        if warehouse is None:
            raise NotFoundError("Warehouse not found")

        def keep(node: Node) -> bool:
            return include_inactive or node.is_active

        overall = CapacityTotals()
        zones = []
        for zone in filter(keep, warehouse.zones):
            zone_totals = CapacityTotals()
            racks = []
            for rack in sorted(
                filter(keep, zone.racks), key=lambda r: (r.distance_to_packing_m, r.code)
            ):
                shelves = []
                for shelf in filter(keep, rack.shelves):
                    bins = [b for b in shelf.bins if keep(b)]
                    for bin_ in bins:
                        _add_to_totals(zone_totals, bin_)
                    shelves.append({**_fields(shelf), "bins": [_fields(b) for b in bins]})
                racks.append({**_fields(rack), "shelves": shelves})
            for name in ("bins", "active_bins", "max_volume_cm3"):
                setattr(overall, name, getattr(overall, name) + getattr(zone_totals, name))
            overall.max_weight_kg += zone_totals.max_weight_kg
            zones.append({**_fields(zone), "totals": zone_totals, "racks": racks})
        return {**_fields(warehouse), "totals": overall, "zones": zones}

    # ------------------------------------------------------------------- create
    def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        if self.db.scalar(select(Warehouse.id).where(Warehouse.code == data.code)):
            raise ConflictError("A warehouse with this code already exists")
        warehouse = Warehouse(**data.model_dump())
        self.db.add(warehouse)
        _commit(self.db, "A warehouse with this code already exists")
        return warehouse

    def create_zone(self, warehouse_id: int, data: ZoneCreate) -> Zone:
        warehouse = self._active_parent(self.get_warehouse(warehouse_id), "Warehouse")
        zone = Zone(warehouse_id=warehouse.id, **data.model_dump())
        self.db.add(zone)
        _commit(self.db, "This warehouse already has a zone with this code")
        return zone

    def create_rack(self, zone_id: int, data: RackCreate) -> Rack:
        zone = self._active_parent(self.get_zone(zone_id), "Zone")
        rack = Rack(zone_id=zone.id, **data.model_dump())
        self.db.add(rack)
        _commit(self.db, "This zone already has a rack with this code")
        return rack

    def create_shelf(self, rack_id: int, data: ShelfCreate) -> Shelf:
        rack = self._active_parent(self.get_rack(rack_id), "Rack")
        shelf = Shelf(rack_id=rack.id, **data.model_dump())
        self.db.add(shelf)
        _commit(self.db, "This rack already has a shelf with this code or level")
        return shelf

    def create_bin(self, shelf_id: int, data: BinCreate) -> Bin:
        shelf = self._active_parent(self.get_shelf(shelf_id), "Shelf")
        bin_ = Bin(
            shelf_id=shelf.id,
            location_code=self._location_code(shelf, data.code),
            **data.model_dump(),
        )
        self.db.add(bin_)
        _commit(self.db, "This shelf already has a bin with this code")
        return bin_

    def generate(self, zone_id: int, data: GenerateLayoutRequest) -> GenerateLayoutResponse:
        """Create racks x shelves x bins in one transaction."""
        zone = self._active_parent(self.get_zone(zone_id), "Zone")
        warehouse_code = zone.warehouse.code
        first_number = self._next_rack_number(zone)
        if first_number + data.racks - 1 > 999:
            raise UnprocessableError("Rack numbers would exceed R999")
        width = 2 if first_number + data.racks - 1 <= 99 else 3

        location_codes: list[str] = []
        try:
            for i in range(data.racks):
                rack = Rack(
                    zone=zone,
                    code=f"R{first_number + i:0{width}d}",
                    distance_to_packing_m=data.first_rack_distance_m + i * data.distance_step_m,
                )
                self.db.add(rack)
                for level in range(1, data.shelves_per_rack + 1):
                    shelf = Shelf(rack=rack, code=f"S{level:02d}", level=level)
                    self.db.add(shelf)
                    for number in range(1, data.bins_per_shelf + 1):
                        code = f"B{number:02d}"
                        location = build_location_code(
                            warehouse_code, zone.code, rack.code, shelf.code, code
                        )
                        location_codes.append(location)
                        self.db.add(
                            Bin(
                                shelf=shelf,
                                code=code,
                                location_code=location,
                                max_weight_kg=data.max_weight_kg,
                                max_volume_cm3=data.max_volume_cm3,
                            )
                        )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(
                "Generation clashes with existing locations; nothing was created"
            ) from exc

        logger.info("Generated %s bins in zone %s", len(location_codes), zone.id)
        return GenerateLayoutResponse(
            racks_created=data.racks,
            shelves_created=data.racks * data.shelves_per_rack,
            bins_created=len(location_codes),
            first_location_code=location_codes[0],
            last_location_code=location_codes[-1],
        )

    # ------------------------------------------------------------------- update
    def update(
        self,
        node: Node,
        data: WarehouseUpdate | ZoneUpdate | RackUpdate | ShelfUpdate | BinUpdate,
    ) -> Node:
        changes = data.model_dump(exclude_unset=True)
        is_active = changes.pop("is_active", None)
        nullable = {"address"}
        for name, value in changes.items():
            if value is not None or name in nullable:
                setattr(node, name, value)

        if is_active is False and node.is_active:
            archived = self._archive_tree(node)
            logger.info("Archived %r and %s record(s) below it", node, archived - 1)
        elif is_active is True and not node.is_active:
            parent = _parent(node)
            if parent is not None and not parent.is_active:
                raise UnprocessableError("Restore the parent first")
            node.is_active = True
        _commit(self.db, "Update conflicts with existing data")
        return node

    # ----------------------------------------------------------------- capacity
    def check_fit(self, bin_id: int, product_id: int, quantity: int) -> FitCheck:
        bin_ = self.get_bin(bin_id)
        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError("Product not found")
        return product_fits_bin(product, bin_, quantity)

    # ------------------------------------------------------------------ helpers
    def _active_parent(self, parent: Node, label: str) -> Any:
        if not parent.is_active:
            raise UnprocessableError(f"{label} is archived")
        return parent

    def _location_code(self, shelf: Shelf, bin_code: str) -> str:
        rack = shelf.rack
        zone = rack.zone
        return build_location_code(zone.warehouse.code, zone.code, rack.code, shelf.code, bin_code)

    def _next_rack_number(self, zone: Zone) -> int:
        numbers = [int(m.group(1)) for r in zone.racks if (m := re.fullmatch(r"R(\d+)", r.code))]
        return max(numbers, default=0) + 1

    def _archive_tree(self, node: Node) -> int:
        count = 0
        stack: list[Node] = [node]
        while stack:
            current = stack.pop()
            if current.is_active:
                current.is_active = False
                count += 1
            stack.extend(_children(current))
        return count


def _fields(node: Node) -> dict[str, Any]:
    """Column values of an ORM row as a dict (relationships excluded)."""
    return {column.key: getattr(node, column.key) for column in node.__table__.columns}


def _add_to_totals(totals: CapacityTotals, bin_: Bin) -> None:
    totals.bins += 1
    if bin_.is_active:
        totals.active_bins += 1
        totals.max_weight_kg += bin_.max_weight_kg
        totals.max_volume_cm3 += bin_.max_volume_cm3
