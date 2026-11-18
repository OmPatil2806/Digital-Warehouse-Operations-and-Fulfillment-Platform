"""Product recommendation features: baskets, customers and their purchase history.

The task: a customer has some products in the basket; which product will they add?
Every model ranks the whole catalogue for a *query*:

- `context`: the other products in the basket (up to MAX_CONTEXT, 0 = padding);
- `customer`: who is ordering;
- `history`: the products of the customer's earlier orders, most recent last (up to
  MAX_HISTORY, only orders placed before this one);

and the *target* is the product that was held out of the basket. Products are numbered
1..n (0 is padding), in product-id order.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import Engine

from training.data import read_frame

MAX_CONTEXT = 10
MAX_HISTORY = 20


@dataclass
class Baskets:
    order_ids: np.ndarray
    customer: np.ndarray  # customer index 1..m
    day: np.ndarray  # datetime64[D]
    items: list[np.ndarray]  # product numbers 1..n per basket (distinct, line order)
    history: np.ndarray  # (orders, MAX_HISTORY) earlier products of the customer
    product_ids: np.ndarray  # product number - 1 -> product id
    categories: np.ndarray  # (n + 1,) category index per product number (0 for padding)
    customers: int

    @property
    def products(self) -> int:
        return len(self.product_ids)

    def subset(self, rows: np.ndarray) -> "Baskets":
        return Baskets(
            self.order_ids[rows],
            self.customer[rows],
            self.day[rows],
            [self.items[i] for i in rows],
            self.history[rows],
            self.product_ids,
            self.categories,
            self.customers,
        )


def load_baskets(engine: Engine) -> Baskets:
    products = read_frame(engine, "SELECT p.id, p.category_id FROM products p ORDER BY p.id")
    number = {pid: i + 1 for i, pid in enumerate(products["id"])}
    categories = np.concatenate([[0], pd.factorize(products["category_id"])[0] + 1])
    lines = read_frame(
        engine,
        "SELECT o.id AS order_id, o.customer_id, date(o.created_at) AS day, oi.product_id "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "ORDER BY o.created_at, o.id, oi.line_number",
    )
    lines["item"] = lines["product_id"].map(number)
    customer_index = {c: i + 1 for i, c in enumerate(sorted(lines["customer_id"].unique()))}
    grouped = lines.groupby("order_id", sort=False)
    order_ids = np.array(list(grouped.groups))
    items = [g["item"].drop_duplicates().to_numpy() for _, g in grouped]
    firsts = grouped.first()
    customer = firsts["customer_id"].map(customer_index).to_numpy()
    history = np.zeros((len(order_ids), MAX_HISTORY), "int32")
    seen: dict[int, list[int]] = {}
    for row, (who, basket) in enumerate(zip(customer, items, strict=True)):
        past = seen.setdefault(int(who), [])
        recent = past[-MAX_HISTORY:]
        if recent:
            history[row, MAX_HISTORY - len(recent) :] = recent
        past.extend(int(i) for i in basket)
        if len(past) > 4 * MAX_HISTORY:
            del past[:-MAX_HISTORY]
    return Baskets(
        order_ids=order_ids,
        customer=customer.astype("int32"),
        day=pd.to_datetime(firsts["day"]).to_numpy("datetime64[D]"),
        items=items,
        history=history,
        product_ids=products["id"].to_numpy(),
        categories=categories.astype("int32"),
        customers=len(customer_index),
    )


@dataclass
class Queries:
    context: np.ndarray  # (n, MAX_CONTEXT)
    customer: np.ndarray  # (n,)
    history: np.ndarray  # (n, MAX_HISTORY)
    target: np.ndarray  # (n,) the held-out product

    def __len__(self) -> int:
        return len(self.target)

    def inputs(self) -> dict[str, np.ndarray]:
        return {"context": self.context, "customer": self.customer, "history": self.history}

    def subset(self, rows: np.ndarray) -> "Queries":
        return Queries(
            self.context[rows], self.customer[rows], self.history[rows], self.target[rows]
        )


def _context(items: np.ndarray) -> np.ndarray:
    row = np.zeros(MAX_CONTEXT, "int32")
    kept = items[:MAX_CONTEXT]
    row[: len(kept)] = kept
    return row


def every_target(baskets: Baskets) -> Queries:
    """Training examples: each product of each basket (2+ products) is a target once,
    the rest of the basket its context."""
    context, customer, history, target = [], [], [], []
    for row, items in enumerate(baskets.items):
        if len(items) < 2:
            continue
        for i, item in enumerate(items):
            context.append(_context(np.delete(items, i)))
            customer.append(baskets.customer[row])
            history.append(baskets.history[row])
            target.append(item)
    return _queries(context, customer, history, target)


def held_out(baskets: Baskets, seed: int, limit: int | None = None) -> Queries:
    """Evaluation queries: one random product held out per basket (2+ products)."""
    rng = np.random.default_rng(seed)
    rows = [r for r, items in enumerate(baskets.items) if len(items) >= 2]
    if limit is not None and len(rows) > limit:
        rows = sorted(rng.choice(rows, limit, replace=False).tolist())
    context, customer, history, target = [], [], [], []
    for row in rows:
        items = baskets.items[row]
        i = int(rng.integers(len(items)))
        context.append(_context(np.delete(items, i)))
        customer.append(baskets.customer[row])
        history.append(baskets.history[row])
        target.append(items[i])
    return _queries(context, customer, history, target)


def _queries(context, customer, history, target) -> Queries:
    if not target:
        raise ValueError("no baskets with two or more products")
    return Queries(
        np.stack(context).astype("int32"),
        np.asarray(customer, "int32"),
        np.stack(history).astype("int32"),
        np.asarray(target, "int32"),
    )
