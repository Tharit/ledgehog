"""Read-only category and payee lists (spec §3.5, §3.6): the filter bar and the rows resolve ids here."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.session import CurrentUser, EngineDep
from app.core.ledger.lookups import list_categories as core_list_categories
from app.core.ledger.lookups import list_payees as core_list_payees

router = APIRouter(prefix="/api/ledger", tags=["lookups"])


class CategoryOut(BaseModel):
    id: int
    parent_id: int | None
    name: str
    kind: str  # "income" | "expense"
    sort_order: int
    icon: str | None
    color: str | None


class CategoriesOut(BaseModel):
    categories: list[CategoryOut]


class PayeeOut(BaseModel):
    id: int
    name: str
    icon: str | None
    color: str | None
    note: str | None


class PayeesOut(BaseModel):
    payees: list[PayeeOut]


@router.get("/categories")
def list_categories(user: CurrentUser, engine: EngineDep) -> CategoriesOut:
    """Every category as a flat list (`parent_id` links the tree): roots first, then `sort_order`, name."""
    with engine.connect() as conn:
        rows = core_list_categories(conn)
    return CategoriesOut(categories=[CategoryOut(**vars(r)) for r in rows])


@router.get("/payees")
def list_payees(user: CurrentUser, engine: EngineDep) -> PayeesOut:
    """Every payee by name: identity and presentation only."""
    with engine.connect() as conn:
        rows = core_list_payees(conn)
    return PayeesOut(payees=[PayeeOut(**vars(r)) for r in rows])
