"""Reads of the category and payee lists the ledger screens need (identity and presentation only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class CategoryRow:
    id: int
    parent_id: int | None
    name: str
    kind: str
    sort_order: int
    icon: str | None
    color: str | None


@dataclass(frozen=True)
class PayeeRow:
    id: int
    name: str
    icon: str | None
    color: str | None
    note: str | None


_CATEGORY = "SELECT id, parent_id, name, kind, sort_order, icon, color FROM category"
_PAYEE = "SELECT id, name, icon, color, note FROM payee"


def _category(r: Any) -> CategoryRow:
    return CategoryRow(r.id, r.parent_id, r.name, r.kind, r.sort_order, r.icon, r.color)


def _payee(r: Any) -> PayeeRow:
    return PayeeRow(r.id, r.name, r.icon, r.color, r.note)


def list_categories(conn: Connection) -> list[CategoryRow]:
    """Every category, flat: roots first, then by `sort_order`, name, id."""
    rows = conn.execute(text(_CATEGORY + " ORDER BY parent_id NULLS FIRST, sort_order, name, id"))
    return [_category(r) for r in rows]


def get_category(conn: Connection, category_id: int) -> CategoryRow | None:
    row = conn.execute(text(_CATEGORY + " WHERE id = :i"), {"i": category_id}).one_or_none()
    return None if row is None else _category(row)


def list_payees(conn: Connection) -> list[PayeeRow]:
    return [_payee(r) for r in conn.execute(text(_PAYEE + " ORDER BY lower(name), name, id"))]


def get_payee(conn: Connection, payee_id: int) -> PayeeRow | None:
    row = conn.execute(text(_PAYEE + " WHERE id = :i"), {"i": payee_id}).one_or_none()
    return None if row is None else _payee(row)
