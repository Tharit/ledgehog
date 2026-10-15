"""Seeding shared by the category and payee write tests."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text


def rule(
    conn: Connection,
    name: str,
    *,
    category_id: int | None = None,
    payee_id: int | None = None,
    condition_payee_id: int | None = None,
) -> int:
    """A rule that sets a category (optionally with a payee condition) or sets a payee."""
    conds = [{"field": "counterparty_ref", "op": "equals", "value": "ref"}]
    if condition_payee_id is not None:
        conds.append({"field": "payee", "op": "is", "value": str(condition_payee_id)})
    sets = "category" if category_id is not None else "payee"
    return int(
        conn.execute(
            text(
                "INSERT INTO rule (sets, category_id, payee_id, conditions, name)"
                " VALUES (:s, :c, :p, CAST(:conds AS jsonb), :n) RETURNING id"
            ),
            {
                "s": sets,
                "c": category_id,
                "p": payee_id,
                "conds": json.dumps(conds),
                "n": name,
            },
        ).scalar_one()
    )


def counts(conn: Connection) -> dict[str, Any]:
    """Row counts and a fingerprint of everything a management write may touch."""
    out: dict[str, Any] = {}
    for table in ("category", "payee", "rule", "ledger_entry"):
        out[table] = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
    out["fingerprint"] = conn.execute(
        text(
            "SELECT (SELECT coalesce(string_agg(c::text, '|' ORDER BY id), '') FROM category c),"
            " (SELECT coalesce(string_agg(p::text, '|' ORDER BY id), '') FROM payee p),"
            " (SELECT coalesce(string_agg(r::text, '|' ORDER BY id), '') FROM rule r),"
            " (SELECT coalesce(string_agg(e.id || ':' || e.version || ':' || coalesce(e.category_id, 0)"
            "   || ':' || coalesce(e.payee_id, 0), '|' ORDER BY e.id), '') FROM ledger_entry e)"
        )
    ).one()
    return out
