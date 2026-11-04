"""Unit tests for product_fits_bin (no database needed)."""

from decimal import Decimal

import pytest

from app.models.catalog import Product
from app.models.warehouse import Bin
from app.services.capacity import product_fits_bin


def product(**overrides: object) -> Product:
    values: dict[str, object] = {
        "sku": "BOX-1",
        "name": "Box",
        "weight_kg": Decimal("2.000"),
        "length_cm": Decimal("10.0"),
        "width_cm": Decimal("10.0"),
        "height_cm": Decimal("10.0"),  # 1 000 cm³
        "is_active": True,
    }
    values.update(overrides)
    return Product(**values)


def bin_(**overrides: object) -> Bin:
    values: dict[str, object] = {
        "code": "B01",
        "location_code": "WH01-ZA-R01-S01-B01",
        "max_weight_kg": Decimal("20.000"),
        "max_volume_cm3": 10_000,
        "is_active": True,
    }
    values.update(overrides)
    return Bin(**values)


def test_fits_exactly_at_the_limits() -> None:
    result = product_fits_bin(product(), bin_(), quantity=10)  # 20 kg, 10 000 cm³

    assert result.fits is True
    assert result.reasons == []
    assert result.required_weight_kg == Decimal("20.000")
    assert result.required_volume_cm3 == Decimal("10000.000")


def test_too_heavy() -> None:
    result = product_fits_bin(product(weight_kg=Decimal("2.001")), bin_(), quantity=10)

    assert result.fits is False
    assert result.reasons == ["Too heavy: needs 20.010 kg, 20.000 kg available"]


def test_too_large() -> None:
    result = product_fits_bin(product(weight_kg=Decimal("0.100")), bin_(), quantity=11)

    assert result.fits is False
    assert result.reasons == ["Too large: needs 11000.000 cm³, 10000 cm³ available"]


def test_existing_contents_reduce_free_capacity() -> None:
    result = product_fits_bin(
        product(),
        bin_(),
        quantity=5,
        current_weight_kg=Decimal("12"),
        current_volume_cm3=Decimal("4000"),
    )

    assert result.fits is False  # 12 + 10 kg > 20 kg; volume 4 000 + 5 000 is still fine
    assert len(result.reasons) == 1
    assert result.reasons[0].startswith("Too heavy")


def test_archived_bin_or_product_never_fits() -> None:
    archived_bin = product_fits_bin(product(), bin_(is_active=False))
    archived_product = product_fits_bin(product(is_active=False), bin_())

    assert archived_bin.reasons == ["Bin is archived"]
    assert archived_product.reasons == ["Product is archived"]


def test_all_problems_are_reported_together() -> None:
    result = product_fits_bin(
        product(weight_kg=Decimal("50")), bin_(is_active=False, max_volume_cm3=100)
    )

    assert len(result.reasons) == 3


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_must_be_positive(quantity: int) -> None:
    with pytest.raises(ValueError):
        product_fits_bin(product(), bin_(), quantity=quantity)
