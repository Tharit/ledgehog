"""Derived entries: the opening, valuations and reconciliations of an account (spec §3.10, §5.10).

`core/balance` is their only writer (architecture §5.1). `recompute_derived` runs inside the
caller's transaction, under the account lock the caller holds; it never locks and never commits.

Per counting record, in order (balance_on, id), the derived entry is

    anchor (the first record):   opening = B - sum(movements dated <= D)
    every later record:          (B - B_prev) - sum(movements dated in (D_prev, D])

where movements are the entries with a source transaction; derived entries never enter a sum.
The stored entries are then reconciled against that: a zero result has no entry, an entry whose
type changed is deleted and recreated (the unique indexes on openings and on the record are not
deferrable, so every delete and demotion precedes every insert), an amount or date that differs
is updated in place, and a second call writes nothing.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import accumulate

from sqlalchemy import Connection, text

from app.core.domain.kinds import INVESTMENT_KINDS


@dataclass(frozen=True)
class Desired:
    type: str
    booked_on: date
    amount: int


def recompute_derived(conn: Connection, account_id: int) -> None:
    """Bring the account's derived entries in line with its records and movements."""
    account = conn.execute(text("SELECT kind, currency FROM account WHERE id = :a"), {"a": account_id}).one()
    desired = _desired(conn, account_id, investment=account.kind in INVESTMENT_KINDS)
    _reconcile(conn, account_id, account.currency, desired)


def _desired(conn: Connection, account_id: int, *, investment: bool) -> dict[int, Desired]:
    records = conn.execute(
        text(
            "SELECT id, balance_on, balance FROM v_balance_record WHERE account_id = :a "
            "ORDER BY balance_on, id"
        ),
        {"a": account_id},
    ).all()
    if not records:
        return {}
    per_day = conn.execute(
        text(
            "SELECT booked_on, sum(amount)::bigint AS total FROM ledger_entry "
            "WHERE account_id = :a AND source_transaction_id IS NOT NULL "
            "GROUP BY booked_on ORDER BY booked_on"
        ),
        {"a": account_id},
    ).all()
    days = [r.booked_on for r in per_day]
    cumulative = [0, *accumulate(int(r.total) for r in per_day)]

    def through(d: date) -> int:
        """Sum of the movements dated on or before `d`."""
        return cumulative[bisect_right(days, d)]

    desired: dict[int, Desired] = {}
    prev_balance = 0
    prev_date: date | None = None
    for r in records:
        if prev_date is None:
            amount = r.balance - through(r.balance_on)
            earliest = min(days[0], r.balance_on) if days else r.balance_on
            entry = Desired("opening", earliest - timedelta(days=1), amount)
        else:
            amount = (r.balance - prev_balance) - (through(r.balance_on) - through(prev_date))
            entry = Desired("valuation" if investment else "reconciliation", r.balance_on, amount)
        if amount != 0:
            desired[r.id] = entry
        prev_balance, prev_date = r.balance, r.balance_on
    return desired


def _reconcile(conn: Connection, account_id: int, currency: str, desired: dict[int, Desired]) -> None:
    stored = {
        r.balance_record_id: r
        for r in conn.execute(
            text(
                "SELECT id, balance_record_id, type, booked_on, amount FROM ledger_entry "
                "WHERE account_id = :a AND balance_record_id IS NOT NULL"
            ),
            {"a": account_id},
        )
    }
    stale = [e.id for rec, e in stored.items() if rec not in desired or e.type != desired[rec].type]
    if stale:
        conn.execute(text("DELETE FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": stale})
    gone = set(stale)
    for rec, want in desired.items():
        have = stored.get(rec)
        if have is None or have.id in gone:
            conn.execute(
                text(
                    "INSERT INTO ledger_entry "
                    "(account_id, balance_record_id, type, amount, currency, booked_on) "
                    "VALUES (:a, :r, :t, :amt, :c, :d)"
                ),
                {
                    "a": account_id,
                    "r": rec,
                    "t": want.type,
                    "amt": want.amount,
                    "c": currency,
                    "d": want.booked_on,
                },
            )
        elif have.amount != want.amount or have.booked_on != want.booked_on:
            conn.execute(
                text("UPDATE ledger_entry SET amount = :amt, booked_on = :d WHERE id = :i"),
                {"amt": want.amount, "d": want.booked_on, "i": have.id},
            )
