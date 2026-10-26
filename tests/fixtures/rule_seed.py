"""Seeding for the rule tests: entries with the source fields a rule reads, and rules.

Commits through whatever connection it is given (an engine's `begin()`), like `ledger_seed`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.plugins.classifier import Condition
from tests.invariants.helpers import make_entry, make_run

DAY = date(2026, 2, 10)


def source(conn: Connection, account_id: int, **cols: Any) -> int:
    """An imported source transaction (columns override the defaults)."""
    values: dict[str, Any] = {
        "origin": "import",
        "importer": "test",
        "import_run_id": make_run(conn, account_id),
        "account_id": account_id,
        "source_id": uuid.uuid4().hex,
        "source_format": "csv",
        "amount": -1000,
        "currency": "EUR",
        "booked_on": DAY,
        "raw": "{}",
    }
    values.update(cols)
    names = ", ".join(values)
    marks = ", ".join(f"CAST(:{c} AS jsonb)" if c == "raw" else f":{c}" for c in values)
    return int(
        conn.execute(
            text(f"INSERT INTO source_transaction ({names}) VALUES ({marks}) RETURNING id"),  # noqa: S608
            values,
        ).scalar_one()
    )


def new_entry(conn: Connection, account_id: int, **cols: Any) -> int:
    """A new, uninterpreted entry (as ingest leaves it): no type, no keys."""
    return make_entry(conn, source(conn, account_id, **cols), type=None)


def confirmed_entry(
    conn: Connection,
    account_id: int,
    *,
    category: int,
    payee: int | None = None,
    keys: dict[str, Any] | None = None,
    **cols: Any,
) -> int:
    """A confirmed flow: `user` keys unless `keys` gives the derivation, and the "none" settling records for
    the document of a confirmed unit (spec §6): a ledger as settling leaves it."""
    derivation = keys
    if derivation is None:
        derivation = {
            "type": {"pass": "user"},
            "category": {"pass": "user"},
            "document": {"pass": "matcher_decision"},
        }
        if payee:
            derivation["payee"] = {"pass": "user"}
    return make_entry(
        conn,
        source(conn, account_id, **cols),
        category_id=category,
        payee_id=payee,
        derivation=json.dumps(derivation),
    )


def payee(conn: Connection, name: str) -> int:
    return int(
        conn.execute(text("INSERT INTO payee (name) VALUES (:n) RETURNING id"), {"n": name}).scalar_one()
    )


def cond(field: str, op: str, value: str) -> Condition:
    return Condition(field, op, value)  # type: ignore[arg-type]


def name_is(value: str) -> Condition:
    return cond("counterparty_name", "equals", value)


def name_starts(value: str) -> Condition:
    return cond("counterparty_name", "starts_with", value)


def payee_is(payee_id: int | str) -> Condition:
    """A payee condition (D215): the payee id as a digit string."""
    return cond("payee", "is", str(payee_id))


def conditions_json(conditions: Sequence[Condition]) -> str:
    return json.dumps([{"field": c.field, "op": c.op, "value": c.value} for c in conditions])


def rule(
    conn: Connection, name: str, sets: str, target: int, conditions: Sequence[Condition] = (), **cols: Any
) -> int:
    """A rule row, written directly (no preview, no settle); `conditions` as `Condition`s."""
    col = {"payee": "payee_id", "category": "category_id", "counter_account": "counter_account_id"}[sets]
    values = {"name": name, "sets": sets, col: target, **cols, "conditions": conditions_json(conditions)}
    names = ", ".join(values)
    marks = ", ".join("CAST(:conditions AS jsonb)" if c == "conditions" else ":" + c for c in values)
    return int(
        conn.execute(
            text(f"INSERT INTO rule ({names}) VALUES ({marks}) RETURNING id"),  # noqa: S608
            values,
        ).scalar_one()
    )


def key(rule_id: int) -> dict[str, Any]:
    return {"pass": "rule", "basis": {"rule_id": rule_id}}
