"""Schemas shared by many endpoints."""

from pydantic import BaseModel


class Page[ItemT](BaseModel):
    """One page of a list result."""

    items: list[ItemT]
    total: int  # number of matching rows across all pages
    offset: int
    limit: int
