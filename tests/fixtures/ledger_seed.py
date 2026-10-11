"""Seeding for the ledger-list tests: entries with exactly the columns a filter looks at.

Works on any connection (rolled-back `db_conn` or a committed engine connection). Movements get
a user-authored source transaction (no import run needed); derived entries get a manual record.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from tests.invariants.helpers import make_balance_record, make_derived_entry, make_entry, make_source

DAY = date(2026, 3, 1)


def account(conn: Connection, name: str = "Giro", currency: str = "EUR", kind: str = "checking") -> int:
    return int(
        conn.execute(
            text("INSERT INTO account (name, kind, currency) VALUES (:n, :k, :c) RETURNING id"),
            {"n": name, "k": kind, "c": currency},
        ).scalar_one()
    )


def category(conn: Connection, name: str, parent: int | None = None, kind: str = "expense") -> int:
    return int(
        conn.execute(
            text("INSERT INTO category (name, kind, parent_id) VALUES (:n, :k, :p) RETURNING id"),
            {"n": name, "k": kind, "p": parent},
        ).scalar_one()
    )


def payee(conn: Connection, name: str) -> int:
    return int(
        conn.execute(text("INSERT INTO payee (name) VALUES (:n) RETURNING id"), {"n": name}).scalar_one()
    )


def tag(conn: Connection, name: str) -> int:
    return int(
        conn.execute(text("INSERT INTO tag (name) VALUES (:n) RETURNING id"), {"n": name}).scalar_one()
    )


def entry(
    conn: Connection,
    account_id: int,
    *,
    amount: int = -1000,
    on: date = DAY,
    currency: str | None = None,
    type: str | None = "flow",
    description: str | None = None,
    note: str | None = None,
    category_id: int | None = None,
    payee_id: int | None = None,
    tags: tuple[int, ...] = (),
    flags: tuple[str, ...] = (),
    counterparty: str | None = None,
    purpose: str | None = None,
    end_to_end_id: str | None = None,
    mandate_ref: str | None = None,
    source_id: int | None = None,
    value_on: date | None = None,
) -> int:
    """A movement entry (its own source transaction unless `source_id` makes it a split sibling)."""
    if currency is None:
        currency = conn.execute(
            text("SELECT currency FROM account WHERE id = :a"), {"a": account_id}
        ).scalar_one()
    if source_id is None:
        source_id = make_source(
            conn, account_id, amount=amount, currency=currency, booked_on=on, importer=None, purpose=purpose
        )
        conn.execute(
            text(
                "UPDATE source_transaction SET counterparty_name = :c, end_to_end_id = :e,"
                " mandate_ref = :m WHERE id = :i"
            ),
            {"c": counterparty, "e": end_to_end_id, "m": mandate_ref, "i": source_id},
        )
    cols: dict[str, Any] = {
        "type": type,
        "description": description,
        "note": note,
        "category_id": category_id,
        "payee_id": payee_id,
        "booked_on": on,
        "value_on": value_on,
    }
    if flags:
        cols["review_flags"] = sorted(flags)
    entry_id = make_entry(conn, source_id, amount=amount, **cols)
    for t in tags:
        conn.execute(
            text("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)"),
            {"e": entry_id, "t": t},
        )
    return entry_id


def source_of(conn: Connection, entry_id: int) -> int:
    return int(
        conn.execute(
            text("SELECT source_transaction_id FROM ledger_entry WHERE id = :i"), {"i": entry_id}
        ).scalar_one()
    )


def derived(
    conn: Connection, account_id: int, *, type: str = "opening", on: date = DAY, amount: int = 5000
) -> int:
    record = make_balance_record(conn, account_id, balance_on=on, balance=amount)
    return make_derived_entry(conn, account_id, record, type=type, booked_on=on, amount=amount)
