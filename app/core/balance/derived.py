"""Derived entries: the opening, valuations and reconciliations of an account (spec §3.10, §5.10).

`core/balance` is their only writer (architecture §5.1). `recompute_derived` runs inside the
caller's transaction, under the account lock the caller holds; it never locks and never commits.

Per counting record, in order (balance_on, id), the derived entry is

    (B - B_prev) - (C - C_prev),   C = sum of the movements dated <= D that the record counts

with B_prev = C_prev = 0 for the anchor (its entry is the opening). A reported record does not count the
late arrivals (spec §3.10). Movements are the account's non-duplicate source transactions; derived entries
never enter a sum.
The stored entries are then reconciled against that: a zero result has no entry, an entry whose
type changed is deleted and recreated (the unique indexes on openings and on the record are not
deferrable, so every delete and demotion precedes every insert), an amount or date that differs
is updated in place, and a second call writes nothing.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
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


DERIVATION_VERSION = 1
"""Raised by a release that changes the formula above; the start sequence recomputes every account's
derived entries when the stored `ledger_setting.derivation_version` differs (architecture §5.7)."""


def recompute_derived(conn: Connection, account_id: int) -> None:
    """Bring the account's derived entries in line with its records and movements."""
    account = conn.execute(text("SELECT kind, currency FROM account WHERE id = :a"), {"a": account_id}).one()
    desired = _desired(conn, account_id, investment=account.kind in INVESTMENT_KINDS)
    _reconcile(conn, account_id, account.currency, desired)


@dataclass(frozen=True)
class Movement:
    """A non-duplicate source transaction, as the derivation sees it.

    `runs` are the runs that delivered it: its own run and the runs of the rows that duplicate it (empty
    for a row no run delivered: user-authored, a booking).
    """

    booked_on: date
    amount: int
    runs: frozenset[int] = frozenset()


@dataclass(frozen=True)
class CountingRecord:
    """A counting balance record with the coverage of its run (None for a manual record)."""

    id: int
    balance_on: date
    balance: int
    run_id: int | None = None
    covered_from: date | None = None
    covered_through: date | None = None


@dataclass(frozen=True)
class DerivationInput:
    """Everything the one rule reads, built by `load_derivation_input` for both its callers."""

    records: tuple[CountingRecord, ...]  # in order (balance_on, id)
    movements: tuple[Movement, ...]
    runs_through: Mapping[int, date | None]  # covered_through of every run that delivered a movement


@dataclass(frozen=True)
class RecordGap:
    """What one counting record owns (spec §3.10).

    `amount` is the derived entry's amount: the opening for the anchor (the first record), the
    reconciliation or valuation for every later one, zero where it owns none. `late_arrivals` is the
    number of movements that are late arrivals for the record.
    """

    record_id: int
    balance_on: date
    balance: int
    anchor: bool
    amount: int
    late_arrivals: int


def load_derivation_input(conn: Connection, account_id: int) -> DerivationInput:
    """The account's counting records and non-duplicate source transactions, with the runs that delivered
    each. By I3 the entries of a non-duplicate source sum to its amount on its dates, so summing sources
    is summing movements."""
    records = tuple(
        CountingRecord(r.id, r.balance_on, int(r.balance), r.import_run_id, r.covered_from, r.covered_through)
        for r in conn.execute(
            text(
                "SELECT b.id, b.balance_on, b.balance, b.import_run_id, r.covered_from, r.covered_through"
                " FROM v_balance_record b LEFT JOIN import_run r ON r.id = b.import_run_id"
                " WHERE b.account_id = :a ORDER BY b.balance_on, b.id"
            ),
            {"a": account_id},
        )
    )
    movements = tuple(
        Movement(
            r.booked_on,
            int(r.amount),
            frozenset(([r.import_run_id] if r.import_run_id is not None else []) + list(r.dup_runs)),
        )
        for r in conn.execute(
            text(
                "SELECT s.booked_on, s.amount, s.import_run_id,"
                " COALESCE((SELECT array_agg(d.import_run_id) FROM source_transaction d"
                "           WHERE d.duplicate_of = s.id AND d.import_run_id IS NOT NULL),"
                "          ARRAY[]::bigint[]) AS dup_runs"
                " FROM source_transaction s WHERE s.account_id = :a AND s.duplicate_of IS NULL"
            ),
            {"a": account_id},
        )
    )
    delivering = {run for m in movements for run in m.runs}
    through = {
        r.id: r.covered_through
        for r in conn.execute(
            text("SELECT id, covered_through FROM import_run WHERE id = ANY(:ids)"),
            {"ids": sorted(delivering)},
        )
    }
    return DerivationInput(records, movements, through)


def record_gaps(data: DerivationInput) -> list[RecordGap]:
    """The one rule behind the derived entries and the statement (architecture §4.1).

    The derived entry of record i is `(B_i - B_(i-1)) - (C_i - C_(i-1))`, `C_i` the sum of the movements
    dated up to D_i that the record counts; B_0 = C_0 = 0, so the anchor's is the opening `B_1 - C_1`.
    A reported record whose run states a coverage does not count the late arrivals: movements dated within
    that coverage that its run did not deliver and that every delivering run delivered after the record,
    i.e. whose runs all cover a date after the record's. A manual record, a record without coverage and a
    movement no run delivered always count.
    """
    moves = sorted(data.movements, key=lambda m: m.booked_on)
    days = [m.booked_on for m in moves]
    cumulative = [0, *accumulate(m.amount for m in moves)]

    def late(rec: CountingRecord, m: Movement) -> bool:
        if not m.runs or rec.run_id in m.runs:
            return False
        for run in m.runs:
            through = data.runs_through.get(run)
            if through is None or through <= rec.balance_on:
                return False
        return True

    gaps: list[RecordGap] = []
    prev_balance, prev_counted = 0, 0
    for rec in data.records:
        hi = bisect_right(days, rec.balance_on)
        counted = cumulative[hi]
        n_late = 0
        if rec.run_id is not None and rec.covered_from is not None and rec.covered_through is not None:
            end = bisect_right(days, min(rec.balance_on, rec.covered_through))
            for m in moves[bisect_left(days, rec.covered_from) : end]:
                if late(rec, m):
                    counted -= m.amount
                    n_late += 1
        gaps.append(
            RecordGap(
                rec.id,
                rec.balance_on,
                rec.balance,
                not gaps,
                (rec.balance - prev_balance) - (counted - prev_counted),
                n_late,
            )
        )
        prev_balance, prev_counted = rec.balance, counted
    return gaps


def _desired(conn: Connection, account_id: int, *, investment: bool) -> dict[int, Desired]:
    data = load_derivation_input(conn, account_id)
    if not data.records:
        return {}
    first_movement = min((m.booked_on for m in data.movements), default=None)
    desired: dict[int, Desired] = {}
    for gap in record_gaps(data):
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
