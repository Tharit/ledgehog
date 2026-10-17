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
from collections.abc import Iterable, Sequence
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


@dataclass(frozen=True)
class RecordGap:
    """What one counting record owns: its interval's movements and the amount left over (spec §3.10).

    `amount` is the derived entry's amount: the opening for the anchor (the first record), the
    reconciliation or valuation for every later one, zero where it owns none. `rows_sum` is the sum of the
    movements in the record's interval: dated up to the record for the anchor, in (previous date, date]
    for the others.
    """

    record_id: int
    balance_on: date
    balance: int
    anchor: bool
    rows_sum: int
    amount: int


def record_gaps(
    records: Sequence[tuple[int, date, int]], movements: Iterable[tuple[date, int]]
) -> list[RecordGap]:
    """The one rule behind the derived entries and the statement's gaps (architecture §4.1).

    `records` are the counting records `(id, balance_on, balance)` in order (balance_on, id);
    `movements` are `(booked_on, amount)` of the account's movements, in any order and any
    grouping. The derived entry of the anchor is `B - sum(movements dated <= D)` and of every later
    record `(B - B_prev) - sum(movements dated in (D_prev, D])`: one formula, the anchor with a
    previous balance and a previous sum of zero.
    """
    per_day: dict[date, int] = {}
    for day, amount in movements:
        per_day[day] = per_day.get(day, 0) + amount
    days = sorted(per_day)
    cumulative = [0, *accumulate(per_day[d] for d in days)]

    def through(d: date) -> int:
        """Sum of the movements dated on or before `d`."""
        return cumulative[bisect_right(days, d)]

    gaps: list[RecordGap] = []
    prev_balance, prev_through = 0, 0
    for rid, on, balance in records:
        here = through(on)
        rows_sum = here - prev_through
        gaps.append(RecordGap(rid, on, balance, not gaps, rows_sum, (balance - prev_balance) - rows_sum))
        prev_balance, prev_through = balance, here
    return gaps


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
    first_movement = per_day[0].booked_on if per_day else None
    desired: dict[int, Desired] = {}
    for gap in record_gaps([(r.id, r.balance_on, r.balance) for r in records], per_day):
        if gap.amount == 0:
            continue
        if gap.anchor:
            earliest = gap.balance_on if first_movement is None else min(first_movement, gap.balance_on)
            desired[gap.record_id] = Desired("opening", earliest - timedelta(days=1), gap.amount)
        else:
            kind = "valuation" if investment else "reconciliation"
            desired[gap.record_id] = Desired(kind, gap.balance_on, gap.amount)
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
