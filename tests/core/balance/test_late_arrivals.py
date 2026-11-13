"""A reported record does not count late arrivals (spec §3.10, D255).

The pure rule first (`record_gaps` on hand-built inputs), then the same rule through the database: the
derived entries and the statement agree on it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Connection

from app.core.balance.derived import (
    CountingRecord,
    DerivationInput,
    Movement,
    RecordGap,
    load_derivation_input,
    record_gaps,
)
from app.core.balance.statement import RecordItem, get_statement
from tests.core.balance.scene import Scene, day
from tests.invariants.helpers import make_balance_record, make_entry, make_run, make_source

Make = Callable[..., int]

D = date


def rec(
    rid: int, on: date, balance: int, run: int | None = None, cov: tuple[date, date] | None = None
) -> CountingRecord:
    return CountingRecord(rid, on, balance, run, *(cov or (None, None)))


def gaps(
    records: list[CountingRecord], movements: list[Movement], runs: dict[int, date | None]
) -> list[tuple[int, int]]:
    out: list[RecordGap] = record_gaps(DerivationInput(tuple(records), tuple(movements), runs))
    return [(g.amount, g.late_arrivals) for g in out]


# ---- pure rule -------------------------------------------------------------------------------


def test_card_late_posting_reconciles_on_neither_record() -> None:
    # statement 1 (run 1, covers Jan 1..Jan 31) balance -100; statement 2 (run 2, Feb 1..Feb 28) balance -250.
    # a purchase dated Jan 30 arrives in run 2: late for record 1
    records = [
        rec(1, D(2026, 1, 31), -100, 1, (D(2026, 1, 1), D(2026, 1, 31))),
        rec(2, D(2026, 2, 28), -250, 2, (D(2026, 2, 1), D(2026, 2, 28))),
    ]
    moves = [
        Movement(D(2026, 1, 10), -100, frozenset({1})),
        Movement(D(2026, 1, 30), -50, frozenset({2})),  # dated in 1's coverage, delivered by 2
        Movement(D(2026, 2, 10), -100, frozenset({2})),
    ]
    # run 2's coverage must reach past record 1's date for the row to be late; run 2's covered_from is Feb 1,
    # so the Jan 30 row lies outside run 2's coverage but inside run 1's: it is late for record 1
    assert gaps(records, moves, {1: D(2026, 1, 31), 2: D(2026, 2, 28)}) == [(0, 1), (0, 0)]


def test_late_posting_at_the_anchor_leaves_no_lasting_difference() -> None:
    records = [
        rec(1, D(2026, 1, 31), -100, 1, (D(2026, 1, 1), D(2026, 1, 31))),
        rec(2, D(2026, 2, 28), -150, 2, (D(2026, 2, 1), D(2026, 2, 28))),
    ]
    moves = [Movement(D(2026, 1, 30), -50, frozenset({2}))]
    got = gaps(records, moves, {1: D(2026, 1, 31), 2: D(2026, 2, 28)})
    assert got == [(-100, 1), (0, 0)]  # opening -100, excludes the late row; then -50 explained


def test_backfill_uploaded_after_the_newer_one_is_order_independent() -> None:
    # newer run 2 (Feb) delivered a January-dated row; backfill run 3 (Jan) is the older record
    records = [
        rec(3, D(2026, 1, 31), -100, 3, (D(2026, 1, 1), D(2026, 1, 31))),
        rec(2, D(2026, 2, 28), -200, 2, (D(2026, 2, 1), D(2026, 2, 28))),
    ]
    moves = [Movement(D(2026, 1, 20), -30, frozenset({2}))]
    got = gaps(records, moves, {2: D(2026, 2, 28), 3: D(2026, 1, 31)})
    assert got == [(-100, 1), (-70, 0)]  # row late for the January record, counted by February's


def test_original_rows_of_a_long_csv_count_for_fints_runs_that_duplicate_them() -> None:
    # run 1: one long CSV, covers Jan 1..Mar 31; run 2: FinTS, Feb 1..Feb 28, its rows are duplicates
    records = [rec(2, D(2026, 2, 28), -100, 2, (D(2026, 2, 1), D(2026, 2, 28)))]
    moves = [Movement(D(2026, 2, 10), -100, frozenset({1, 2}))]
    assert gaps(records, moves, {1: D(2026, 3, 31), 2: D(2026, 2, 28)}) == [(0, 0)]


def test_a_delivering_run_covering_through_the_record_date_means_not_late() -> None:
    records = [rec(2, D(2026, 2, 28), -100, 2, (D(2026, 2, 1), D(2026, 2, 28)))]
    moves = [Movement(D(2026, 2, 10), -100, frozenset({1}))]
    assert gaps(records, moves, {1: D(2026, 2, 28), 2: D(2026, 2, 28)}) == [(0, 0)]  # counted
    assert gaps(records, moves, {1: None, 2: D(2026, 2, 28)}) == [(0, 0)]  # null coverage end: counted


def test_gap_fill_spanning_a_record_leaves_a_cancelling_pair() -> None:
    # the bank's balance at Jan 31 includes a Jan 15 row that run 1 did not deliver; a gap-fill file
    # (run 3, Jan 1..Mar 31) delivers it afterwards: late for record 1, counted by record 2
    records = [
        rec(0, D(2025, 12, 31), 0),
        rec(1, D(2026, 1, 31), -50, 1, (D(2026, 1, 20), D(2026, 1, 31))),
        rec(2, D(2026, 2, 28), -50, 2, (D(2026, 2, 1), D(2026, 2, 28))),
    ]
    moves = [Movement(D(2026, 1, 15), -50, frozenset({3}))]
    runs = {1: D(2026, 1, 31), 2: D(2026, 2, 28), 3: D(2026, 3, 31)}
    # the row lies outside run 1's coverage here (it starts Jan 20): not late, counted, no pair
    assert gaps(records, moves, runs) == [(0, 0), (0, 0), (0, 0)]
    spanning = [*records[:1], rec(1, D(2026, 1, 31), -50, 1, (D(2026, 1, 1), D(2026, 1, 31))), records[2]]
    assert gaps(spanning, moves, runs) == [(0, 0), (-50, 1), (50, 0)]  # the pair cancels


def test_gap_fill_ending_before_the_record_date_is_not_late() -> None:
    records = [rec(1, D(2026, 1, 31), -50, 1, (D(2026, 1, 1), D(2026, 1, 31)))]
    moves = [Movement(D(2026, 1, 15), -50, frozenset({3}))]
    assert gaps(records, moves, {1: D(2026, 1, 31), 3: D(2026, 1, 20)}) == [(0, 0)]


def test_manual_record_without_coverage_and_user_entered_movements_count_everything() -> None:
    moves = [Movement(D(2026, 1, 15), -50, frozenset({3})), Movement(D(2026, 1, 16), -20, frozenset())]
    runs = {3: D(2026, 3, 31)}
    assert gaps([rec(1, D(2026, 1, 31), -70)], moves, runs) == [(0, 0)]  # manual
    assert gaps([rec(1, D(2026, 1, 31), -70, 1)], moves, runs) == [(0, 0)]  # run without coverage
    covered = rec(1, D(2026, 1, 31), -70, 1, (D(2026, 1, 1), D(2026, 1, 31)))
    assert gaps([covered], moves, runs) == [(-50, 1)]  # the user-entered -20 is never late: opening -70 + 20


def test_a_missing_row_leaves_a_lasting_difference_and_a_duplicated_row_too() -> None:
    cov1, cov2 = (D(2026, 1, 1), D(2026, 1, 31)), (D(2026, 2, 1), D(2026, 2, 28))
    records = [rec(1, D(2026, 1, 31), 0, 1, cov1), rec(2, D(2026, 2, 28), -100, 2, cov2)]
    runs = {1: D(2026, 1, 31), 2: D(2026, 2, 28)}
    missing = [Movement(D(2026, 2, 5), -60, frozenset({2}))]  # the bank saw -100, the rows say -60
    assert gaps(records, missing, runs) == [(0, 0), (-40, 0)]
    duplicated = [
        Movement(D(2026, 2, 5), -100, frozenset({2})),
        Movement(D(2026, 2, 5), -100, frozenset({2})),
    ]
    assert gaps(records, duplicated, runs) == [(0, 0), (100, 0)]


# ---- through the database --------------------------------------------------------------------


def test_the_database_inputs_carry_duplicates_runs_and_coverage(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    csv = make_run(db_conn, s.account, covered_from=day(1, 1), covered_through=day(3, 31))
    fints = make_run(db_conn, s.account, covered_from=day(2, 1), covered_through=day(2, 28))
    original = make_source(db_conn, s.account, amount=-100, booked_on=day(2, 10), run_id=csv)
    make_entry(db_conn, original)
    make_source(db_conn, s.account, amount=-100, booked_on=day(2, 10), run_id=fints, duplicate_of=original)
    make_source(db_conn, s.account, amount=-5, booked_on=day(2, 11), importer=None)
    make_balance_record(db_conn, s.account, balance_on=day(2, 28), balance=-100, run_id=fints)
    data = load_derivation_input(db_conn, s.account)
    assert sorted((m.amount, m.runs) for m in data.movements) == [
        (-100, frozenset({csv, fints})),
        (-5, frozenset()),
    ]
    assert (data.records[0].covered_from, data.records[0].covered_through) == (day(2, 1), day(2, 28))
    assert data.runs_through == {csv: day(3, 31), fints: day(2, 28)}


def test_a_card_late_posting_is_in_the_statement_and_the_entries_agree(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    run1 = make_run(db_conn, s.account, covered_from=day(1, 1), covered_through=day(1, 31))
    run2 = make_run(db_conn, s.account, covered_from=day(2, 1), covered_through=day(2, 28))
    make_entry(db_conn, make_source(db_conn, s.account, amount=-100, booked_on=day(1, 10), run_id=run1))
    make_entry(db_conn, make_source(db_conn, s.account, amount=-50, booked_on=day(1, 30), run_id=run2))
    make_entry(db_conn, make_source(db_conn, s.account, amount=-10, booked_on=day(2, 10), run_id=run2))
    first = make_balance_record(db_conn, s.account, balance_on=day(1, 31), balance=-100, run_id=run1)
    second = make_balance_record(db_conn, s.account, balance_on=day(2, 28), balance=-160, run_id=run2)
    s.recompute()
    items = {i.id: i for i in get_statement(db_conn, s.account).items if isinstance(i, RecordItem)}
    assert (items[first].difference, items[first].late_arrivals) == (0, 1)  # the opening, without the -50
    assert (items[second].difference, items[second].late_arrivals) == (0, 0)
    assert s.derived_of(first) is None
    assert s.derived_of(second) is None
    s.check()
