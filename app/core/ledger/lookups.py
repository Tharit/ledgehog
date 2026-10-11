"""Read-only lists the ledger screens need: categories and payees (presentation and identity only)."""

from __future__ import annotations

from dataclasses import dataclass

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


def list_categories(conn: Connection) -> list[CategoryRow]:
    """Every category, flat: roots first, then by `sort_order`, name, id."""
    rows = conn.execute(
        text(
            "SELECT id, parent_id, name, kind, sort_order, icon, color FROM category"
            " ORDER BY parent_id NULLS FIRST, sort_order, name, id"
        )
    )
    return [CategoryRow(r.id, r.parent_id, r.name, r.kind, r.sort_order, r.icon, r.color) for r in rows]


def list_payees(conn: Connection) -> list[PayeeRow]:
    rows = conn.execute(text("SELECT id, name, icon, color, note FROM payee ORDER BY lower(name), name, id"))
    return [PayeeRow(r.id, r.name, r.icon, r.color, r.note) for r in rows]
