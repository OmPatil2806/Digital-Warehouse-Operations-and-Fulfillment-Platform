"""Physical capacity rules: can a quantity of a product be stored in a bin?

Used by the layout API now and by put-away / transfers in Phase 4.

Bins are described by their maximum weight and volume (project document, section 9),
so the check compares total weight and total volume. `current_*` lets Phase 4 pass in
what is already stored in the bin.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.catalog import Product
from app.models.warehouse import Bin


@dataclass(frozen=True)
class FitCheck:
    fits: bool
    required_weight_kg: Decimal
    required_volume_cm3: Decimal
    reasons: list[str] = field(default_factory=list)


def product_fits_bin(
    product: Product,
    bin_: Bin,
    quantity: int = 1,
    *,
    current_weight_kg: Decimal = Decimal("0"),
    current_volume_cm3: Decimal = Decimal("0"),
) -> FitCheck:
    """Check whether `quantity` units of `product` fit into `bin_` on top of its contents."""
    if quantity < 1:
        raise ValueError("quantity must be at least 1")

    weight = product.weight_kg * quantity
    volume = product.volume_cm3 * quantity
    reasons: list[str] = []

    if not bin_.is_active:
        reasons.append("Bin is archived")
    if not product.is_active:
        reasons.append("Product is archived")
    if current_weight_kg + weight > bin_.max_weight_kg:
        free = bin_.max_weight_kg - current_weight_kg
        reasons.append(f"Too heavy: needs {weight} kg, {free} kg available")
    if current_volume_cm3 + volume > bin_.max_volume_cm3:
        free_volume = Decimal(bin_.max_volume_cm3) - current_volume_cm3
        reasons.append(f"Too large: needs {volume} cm³, {free_volume} cm³ available")

    return FitCheck(
        fits=not reasons,
        required_weight_kg=weight,
        required_volume_cm3=volume,
        reasons=reasons,
    )
