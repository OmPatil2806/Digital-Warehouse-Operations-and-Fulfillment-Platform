"""Customers: create, update, and which customer a login belongs to."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, UnprocessableError
from app.models.order import Customer
from app.models.user import RoleName, User
from app.schemas.order import CustomerCreate, CustomerUpdate


class CustomerNotFoundError(NotFoundError):
    message = "Customer not found"


class CustomerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, customer_id: int) -> Customer:
        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise CustomerNotFoundError()
        return customer

    def for_user(self, user: User) -> Customer | None:
        return self.db.scalar(select(Customer).where(Customer.user_id == user.id))

    def scope_for(self, user: User) -> int | None:
        """None = the user sees every customer (warehouse roles); otherwise their customer id.

        A customer login that is not linked to a customer may not see any orders.
        """
        if user.has_role(RoleName.ADMIN, RoleName.MANAGER, RoleName.STAFF):
            return None
        customer = self.for_user(user)
        if customer is None or not customer.is_active:
            raise PermissionDeniedError("Your login is not linked to an active customer account")
        return customer.id

    def create(self, data: CustomerCreate) -> Customer:
        values = data.model_dump()
        values["code"] = (values["code"] or self._next_code()).upper()
        self._check_login(values.get("user_id"))
        customer = Customer(**values)
        self.db.add(customer)
        self._commit()
        return customer

    def update(self, customer_id: int, data: CustomerUpdate) -> Customer:
        customer = self.get(customer_id)
        changes = data.model_dump(exclude_unset=True)
        if "user_id" in changes:
            self._check_login(changes["user_id"], exclude_customer_id=customer.id)
        for name, value in changes.items():
            if value is not None or name in {"email", "phone", "user_id"}:
                setattr(customer, name, value)
        self._commit()
        return customer

    def _check_login(self, user_id: int | None, exclude_customer_id: int | None = None) -> None:
        if user_id is None:
            return
        user = self.db.get(User, user_id)
        if user is None:
            raise UnprocessableError("User not found")
        if RoleName.CUSTOMER not in user.role_names:
            raise UnprocessableError(f"{user.email} does not have the customer role")
        taken = self.db.scalar(
            select(Customer.code).where(
                Customer.user_id == user_id,
                Customer.id != (exclude_customer_id or 0),
            )
        )
        if taken:
            raise ConflictError(f"{user.email} is already linked to customer {taken}")

    def _next_code(self) -> str:
        last = self.db.scalar(select(func.max(Customer.code)).where(Customer.code.like("CUST-%")))
        number = int(last.removeprefix("CUST-")) + 1 if last and last[5:].isdigit() else 1
        return f"CUST-{number:04d}"

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("A customer with this code already exists") from exc
