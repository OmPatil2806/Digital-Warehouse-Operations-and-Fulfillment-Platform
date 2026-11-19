"""Orders stay consistent when something goes wrong halfway.

These paths cannot be reached by normal use, so the failure is simulated: two
requests taking the same order number at once, and the stock reservation failing
after the order was already marked confirmed.
"""

import pytest
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.models.order import Order
from app.schemas.inventory import ReceiveRequest
from app.schemas.order import OrderCreate
from app.services.allocation_service import AllocationService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderService
from tests.factories import create_bin, create_category, create_customer, create_product


@pytest.fixture()
def order_input(db_session: Session) -> OrderCreate:
    product = create_product(db_session, create_category(db_session))
    InventoryService(db_session).receive(
        ReceiveRequest(product_id=product.id, bin_id=create_bin(db_session).id, quantity=5),
        user=None,
    )
    customer = create_customer(db_session)
    return OrderCreate(customer_id=customer.id, items=[{"product_id": product.id, "quantity": 2}])


def test_two_orders_with_the_same_number_conflict(
    db_session: Session, order_input: OrderCreate, monkeypatch: pytest.MonkeyPatch
):
    service = OrderService(db_session)
    first = service.create(order_input, user=None)
    # The second request computed its number before the first one was saved.
    monkeypatch.setattr(OrderService, "_next_order_number", lambda self: first.order_number)
    with pytest.raises(ConflictError, match="try again"):
        service.create(order_input, user=None)
    assert db_session.query(Order).count() == 1  # nothing half-created


@pytest.mark.parametrize("method", ["confirm", "reserve_stock"])
def test_a_failed_reservation_leaves_the_order_unchanged(
    db_session: Session,
    order_input: OrderCreate,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
):
    service = OrderService(db_session)
    order = service.create(order_input, user=None)
    if method == "reserve_stock":  # an order waiting for stock
        order.status = "backordered"
        db_session.commit()
    before = order.status

    def broken(self, order, *, user):
        raise RuntimeError("database went away")

    monkeypatch.setattr(AllocationService, "reserve_for_order", broken)
    with pytest.raises(RuntimeError):
        getattr(service, method)(order.id, user=None)
    db_session.expire_all()
    order = db_session.get(Order, order.id)
    assert order.status == before  # the confirmation was rolled back with the reservation
    assert "confirmed" not in {h.to_status for h in order.history}
