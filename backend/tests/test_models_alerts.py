"""Tests for the alerts table."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import Alert, AlertSeverity, AlertStatus, AlertType
from tests.factories import create_category, create_product


def low_stock(product_id: int, **overrides: object) -> Alert:
    values: dict[str, object] = {
        "alert_type": AlertType.LOW_STOCK,
        "severity": AlertSeverity.WARNING,
        "dedup_key": f"low_stock:product:{product_id}",
        "title": "Low stock",
        "product_id": product_id,
    }
    values.update(overrides)
    return Alert(**values)


def test_only_one_unresolved_alert_per_cause(db_session: Session):
    product = create_product(db_session, create_category(db_session))
    first = low_stock(product.id)
    db_session.add(first)
    db_session.commit()
    assert first.status == AlertStatus.OPEN

    db_session.add(low_stock(product.id))
    with pytest.raises(IntegrityError, match="UNIQUE"):
        db_session.commit()
    db_session.rollback()

    # Once resolved, the same cause can raise a new alert (history is kept).
    first.status = AlertStatus.RESOLVED
    db_session.commit()
    db_session.add(low_stock(product.id))
    db_session.commit()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"alert_type": "fire"}, "valid_alert_type"),
        ({"severity": "panic"}, "valid_severity"),
        ({"status": "ignored"}, "valid_status"),
    ],
)
def test_invalid_alert_values_are_rejected(db_session: Session, overrides: dict, constraint: str):
    db_session.add(low_stock(None, dedup_key="x", **overrides))
    with pytest.raises(IntegrityError, match=constraint):
        db_session.commit()
    db_session.rollback()
