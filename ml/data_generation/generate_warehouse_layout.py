"""Warehouses > zones > racks > shelves > bins (project document, section 9.3).

Rules that later stages and the ML use cases rely on:

- Every warehouse has a picking zone near the packing station, and always a returns
  zone; bigger warehouses add bulk, cold, hazardous and a second picking zone.
- Racks lie further from packing the higher their number (walking distance).
- Low shelves carry more weight: heavy items belong on level 1 (slotting).
- Bulk bins are large, cold and hazardous bins smaller.
"""

from decimal import Decimal

from app.models import Bin, Rack, Shelf, Warehouse, Zone, build_location_code
from data_generation import catalog_data as data
from data_generation.context import BinInfo, GenerationContext

# Per zone type: (max weight kg on level 2, max volume cm³)
BIN_CAPACITY = {
    "picking": (150, 150_000),
    "bulk": (600, 1_500_000),
    "cold": (120, 120_000),
    "hazardous": (200, 200_000),
    "returns": (150, 300_000),
}
LEVEL_WEIGHT_FACTOR = {1: 2.0, 2: 1.0, 3: 0.6}  # higher levels: 0.4
RACK_SPACING_M = 4.0


def zone_specs(count: int) -> list[tuple[str, str, str, int]]:
    """The zones of one warehouse: the first `count - 1` standard zones plus returns."""
    if count < 2:
        raise ValueError("a warehouse needs at least a picking and a returns zone")
    if count - 1 > len(data.ZONE_SPECS):
        raise ValueError(f"at most {len(data.ZONE_SPECS) + 1} zones per warehouse")
    return [*data.ZONE_SPECS[: count - 1], data.RETURNS_ZONE]


def max_weight(zone_type: str, level: int) -> Decimal:
    base, _volume = BIN_CAPACITY[zone_type]
    return Decimal(f"{base * LEVEL_WEIGHT_FACTOR.get(level, 0.4):.3f}")


def generate_warehouse_layout(ctx: GenerationContext) -> None:
    config = ctx.config
    if config.warehouses > len(data.WAREHOUSES):
        raise ValueError(f"at most {len(data.WAREHOUSES)} warehouses are available")
    rng = ctx.rng("layout")
    stamp = {"created_at": ctx.start_time, "updated_at": ctx.start_time}
    warehouses, zones, racks, shelves, bins = [], [], [], [], []

    for w, (wh_code, wh_name, address) in enumerate(data.WAREHOUSES[: config.warehouses], 1):
        warehouses.append(
            {"id": w, "code": wh_code, "name": wh_name, "address": address, "is_active": True}
            | stamp
        )
        ctx.warehouse_ids.append(w)
        for zone_code, zone_name, zone_type, first_distance in zone_specs(
            config.zones_per_warehouse
        ):
            zone_id = len(zones) + 1
            zones.append(
                {
                    "id": zone_id,
                    "warehouse_id": w,
                    "code": zone_code,
                    "name": zone_name,
                    "zone_type": zone_type,
                    "is_active": True,
                }
                | stamp
            )
            for r in range(1, config.racks_per_zone + 1):
                rack_id = len(racks) + 1
                rack_code = f"R{r:02d}"
                distance = first_distance + (r - 1) * RACK_SPACING_M + float(rng.uniform(0, 1.5))
                racks.append(
                    {
                        "id": rack_id,
                        "zone_id": zone_id,
                        "code": rack_code,
                        "distance_to_packing_m": Decimal(f"{distance:.1f}"),
                        "is_active": True,
                    }
                    | stamp
                )
                for level in range(1, config.shelves_per_rack + 1):
                    shelf_id = len(shelves) + 1
                    shelf_code = f"S{level:02d}"
                    shelves.append(
                        {
                            "id": shelf_id,
                            "rack_id": rack_id,
                            "code": shelf_code,
                            "level": level,
                            "is_active": True,
                        }
                        | stamp
                    )
                    for b in range(1, config.bins_per_shelf + 1):
                        bin_id = len(bins) + 1
                        bin_code = f"B{b:02d}"
                        weight = max_weight(zone_type, level)
                        volume = BIN_CAPACITY[zone_type][1]
                        bins.append(
                            {
                                "id": bin_id,
                                "shelf_id": shelf_id,
                                "code": bin_code,
                                "location_code": build_location_code(
                                    wh_code, zone_code, rack_code, shelf_code, bin_code
                                ),
                                "max_weight_kg": weight,
                                "max_volume_cm3": volume,
                                "is_active": True,
                            }
                            | stamp
                        )
                        ctx.bins.append(
                            BinInfo(
                                id=bin_id,
                                warehouse_id=w,
                                zone_type=zone_type,
                                level=level,
                                distance_m=round(distance, 1),
                                max_weight_kg=weight,
                                max_volume_cm3=volume,
                            )
                        )

    for model, rows in (
        (Warehouse, warehouses),
        (Zone, zones),
        (Rack, racks),
        (Shelf, shelves),
        (Bin, bins),
    ):
        ctx.writer.insert(model.__table__, rows)
