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

from bisect import bisect_left
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


DERIVATION_VERSION = 2
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

    `arrived` is the earliest coverage end among the runs that delivered it, as the row, as a duplicate
    of it or as an earlier delivery ingest skipped (None for a row no run delivered: user-authored,
    a booking).
    `missed` says that some run covers its date and ends before it arrived (spec §3.10).
    """

    booked_on: date
    amount: int
    arrived: date | None = None
    missed: bool = False


@dataclass(frozen=True)
class CountingRecord:
    """A counting balance record with its run and the coverage end of that run (None for a manual record)."""

    id: int
    balance_on: date
    balance: int
    run_id: int | None = None
    covered_through: date | None = None


@dataclass(frozen=True)
class DerivationInput:
    """Everything the one rule reads, built by `load_derivation_input` for both its callers."""

    records: tuple[CountingRecord, ...]  # in order (balance_on, id)
    movements: tuple[Movement, ...]


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


_MOVEMENTS_SQL = """
WITH deliveries AS (
    SELECT COALESCE(s.duplicate_of, s.id) AS movement_id, s.import_run_id AS run_id
    FROM source_transaction s
    WHERE s.account_id = :a AND s.import_run_id IS NOT NULL
  UNION ALL
    SELECT COALESCE(s.duplicate_of, s.id), k.import_run_id
    FROM source_transaction_earlier_delivery k JOIN source_transaction s ON s.id = k.source_transaction_id
    WHERE s.account_id = :a
)
SELECT m.booked_on, m.amount, min(r.covered_through) AS arrived
FROM source_transaction m
LEFT JOIN deliveries d ON d.movement_id = m.id
LEFT JOIN import_run r ON r.id = d.run_id
WHERE m.account_id = :a AND m.duplicate_of IS NULL
GROUP BY m.id, m.booked_on, m.amount
"""


def load_derivation_input(conn: Connection, account_id: int) -> DerivationInput:
    """The account's counting records and non-duplicate source transactions, each with when it arrived and
    whether a run missed it. By I3 the entries of a non-duplicate source sum to its amount on its dates,
    so summing sources is summing movements."""
    records = tuple(
        CountingRecord(r.id, r.balance_on, int(r.balance), r.import_run_id, r.covered_through)
        for r in conn.execute(
            text(
                "SELECT b.id, b.balance_on, b.balance, b.import_run_id, r.covered_through"
                " FROM v_balance_record b LEFT JOIN import_run r ON r.id = b.import_run_id"
                " WHERE b.account_id = :a ORDER BY b.balance_on, b.id"
            ),
            {"a": account_id},
        )
    )
    runs = sorted(
        (r.covered_through, r.covered_from)
        for r in conn.execute(
            text(
                "SELECT covered_from, covered_through FROM import_run"
                " WHERE account_id = :a AND emits = 'transactions' AND status = 'ok'"
                " AND covered_from IS NOT NULL AND covered_through IS NOT NULL"
            ),
            {"a": account_id},
        )
    )
    ends = [through for through, _ in runs]

    def missed(booked_on: date, arrived: date) -> bool:
        # a run covering the date that ended before the movement arrived; the first one found decides
        stop = bisect_left(ends, arrived)
        return any(runs[i][1] <= booked_on for i in range(bisect_left(ends, booked_on), stop))

    movements = tuple(
        Movement(
            r.booked_on, int(r.amount), r.arrived, r.arrived is not None and missed(r.booked_on, r.arrived)
        )
        for r in conn.execute(text(_MOVEMENTS_SQL), {"a": account_id})
    )
    return DerivationInput(records, movements)


def record_gaps(data: DerivationInput) -> list[RecordGap]:
    """The one rule behind the derived entries and the statement (architecture §4.1).

    The derived entry of record i is `(B_i - B_(i-1)) - (C_i - C_(i-1))`, `C_i` the sum of the movements
    dated up to D_i that the record counts; B_0 = C_0 = 0, so the anchor's is the opening `B_1 - C_1`.
    A reported record whose run states a coverage does not count the late arrivals: movements dated up to
    its date that were missed and arrived after that coverage ended. A manual record, a record without
    coverage and a movement no run delivered always count.

    Records are walked in order with the missed movements dated so far; one whose arrival is on or before
    a record's date is late for no later record either (a record's coverage reaches its date), so it
    leaves the list for good.
    """
    moves = sorted(data.movements, key=lambda m: m.booked_on)
    cumulative = [0, *accumulate(m.amount for m in moves)]
    entered = 0
    open_missed: list[Movement] = []  # dated up to the record, missed, not yet arrived by its date
    gaps: list[RecordGap] = []
    prev_balance, prev_counted = 0, 0
    for rec in data.records:
        while entered < len(moves) and moves[entered].booked_on <= rec.balance_on:
            if moves[entered].missed:
                open_missed.append(moves[entered])
            entered += 1
        open_missed = [m for m in open_missed if m.arrived is not None and m.arrived > rec.balance_on]
        counted = cumulative[entered]
        n_late = 0
        if rec.covered_through is not None:
            for m in open_missed:
                if m.arrived is not None and m.arrived > rec.covered_through:
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
