"""What the reporting tests share: rates, the number a drill-down shows, a seeded household."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.ledger import LedgerFilter, list_entries
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import make_balance_record, make_derived_entry, pair


def rate(conn: Connection, currency: str, on: date, per_base: str) -> None:
    conn.execute(
        text("INSERT INTO fx_rate (currency, rate_date, per_base) VALUES (:c, :d, CAST(:r AS numeric))"),
        {"c": currency, "d": on, "r": per_base},
    )


def listed(conn: Connection, **kw: Any) -> int:
    """What the ledger list counts for a filter: the number a drill-down shows."""
    return list_entries(conn, LedgerFilter(**kw), limit=1, offset=0).total


def listed_base_sum(conn: Connection, flt: LedgerFilter) -> int | None:
    """The sum of the base values of the entries the ledger list holds for `flt` (None: none valued)."""
    entries = list_entries(conn, flt, limit=500, offset=0).entries
    assert len(entries) < 500
    ids = [e.id for e in entries]
    if not ids:
        return 0
    return conn.execute(  # type: ignore[no-any-return]
        text("SELECT sum(base_value(amount, currency, booked_on)) FROM ledger_entry WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).scalar_one()


@dataclass(frozen=True)
class Household:
    """A seeded ledger with every kind of cell a report has; `today` is 2026-10-20."""

    giro: int
    cash: int
    usd: int  # a USD account (no rate: unvalued unless a test adds one)
    food: int  # expense roots
    groceries: int  # child of food
    travel: int
    salary: int  # income roots
    gifts: int
    trip: int  # a tag


TODAY = date(2026, 10, 20)


def household(conn: Connection) -> Household:
    """Flows in two months of both kinds with refunds, a parent with its own entries, an opposite-sign root,
    unclassified of both signs and an untyped entry, a reconciliation, unpaired and paired transfers, a
    foreign account with no rate, a tag and an unconfirmed entry."""
    g = seed.account(conn, "Giro")
    c = seed.account(conn, "Cash", kind="cash")
    u = seed.account(conn, "Travel card", currency="USD", kind="card")
    food = seed.category(conn, "Food")
    groceries = seed.category(conn, "Groceries", parent=food)
    travel = seed.category(conn, "Travel")
    salary = seed.category(conn, "Salary", kind="income")
    gifts = seed.category(conn, "Gifts", kind="income")
    trip = seed.tag(conn, "trip")
    d = date
    e = seed.entry
    seed.derived(conn, g, type="opening", on=d(2026, 8, 1), amount=100_000)
    seed.derived(conn, c, type="opening", on=d(2026, 8, 1), amount=5_000)
    usd_record = make_balance_record(conn, u, balance_on=d(2026, 8, 1), balance=30_000, currency="USD")
    make_derived_entry(
        conn, u, usd_record, type="opening", booked_on=d(2026, 8, 1), amount=30_000, currency="USD"
    )
    # September
    e(conn, g, amount=300_000, on=d(2026, 9, 1), category_id=salary)
    e(conn, g, amount=-8_000, on=d(2026, 9, 3), category_id=groceries)
    e(conn, g, amount=-2_000, on=d(2026, 9, 4), category_id=food)  # the parent's own entry
    e(conn, g, amount=500, on=d(2026, 9, 5), category_id=groceries)  # a refund
    e(conn, g, amount=-40_000, on=d(2026, 9, 30), category_id=travel, tags=(trip,))
    e(conn, g, amount=-1_500, on=d(2026, 9, 30))  # unclassified out (no category)
    # October
    e(conn, g, amount=300_000, on=d(2026, 10, 1), category_id=salary)
    e(conn, g, amount=-9_000, on=d(2026, 10, 2), category_id=groceries, flags=("unconfirmed",))
    e(conn, g, amount=700, on=d(2026, 10, 3), category_id=travel)  # October's travel nets to the other sign
    e(conn, g, amount=1_000, on=d(2026, 10, 6), category_id=gifts)
    e(conn, g, amount=2_500, on=d(2026, 10, 7))  # unclassified in
    e(conn, g, amount=-300, on=d(2026, 10, 8), type=None)  # not interpreted yet: unclassified out
    e(conn, c, amount=-1_200, on=d(2026, 10, 9), category_id=groceries)
    e(conn, u, amount=-2_000, on=d(2026, 10, 10), category_id=travel, tags=(trip,))  # USD, unvalued
    seed.derived(conn, g, type="reconciliation", on=d(2026, 10, 12), amount=-700)
    # a paired transfer (Giro -> Cash) and two unpaired legs
    w = e(conn, g, amount=-5_000, on=d(2026, 10, 14), type="transfer")
    k = e(conn, c, amount=5_000, on=d(2026, 10, 14), type="transfer")
    pair(conn, w, k)
    conn.execute(
        text(
            "UPDATE ledger_entry SET counter_account_id = CASE id WHEN :w THEN :c ELSE :g END"
            " WHERE id IN (:w, :k)"
        ),
        {"w": w, "k": k, "c": c, "g": g},
    )
    e(conn, g, amount=-4_000, on=d(2026, 10, 15), type="transfer", flags=("waiting",))
    e(conn, g, amount=-3_000, on=d(2026, 10, 16), type="transfer", flags=("unmatched_transfer",))
    return Household(g, c, u, food, groceries, travel, salary, gifts, trip)
