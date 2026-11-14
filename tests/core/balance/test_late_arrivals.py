"""A reported record does not count late arrivals (spec §3.10, D255).

The pure rule first (`record_gaps` on hand-built inputs), then the same rule through the database: the
derived entries and the statement agree on it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Connection, text

from app.core.balance.derived import (
    CountingRecord,
    DerivationInput,
    Movement,
    RecordGap,
    load_derivation_input,
    record_gaps,
    record_gaps_with_late_for,
)
from app.core.balance.statement import RecordItem, SourceItem, get_statement
from tests.core.balance.scene import Scene, day
from tests.invariants.helpers import make_balance_record, make_entry, make_run, make_source

Make = Callable[..., int]

D = date


def rec(rid: int, on: date, balance: int, through: date | None = None) -> CountingRecord:
    return CountingRecord(rid, on, balance, rid if through else None, through)


def mv(
    on: date, amount: int, arrived: date | None = None, missed: bool = False, mid: int = 0
) -> Movement:
    return Movement(on, amount, arrived, missed, mid)


def gaps(records: list[CountingRecord], movements: list[Movement]) -> list[tuple[int, int]]:
    out: list[RecordGap] = record_gaps(DerivationInput(tuple(records), tuple(movements)))
    return [(g.amount, g.late_arrivals) for g in out]


# ---- pure rule -------------------------------------------------------------------------------


def test_card_late_posting_reconciles_on_neither_record() -> None:
    # statement 1 (covers through Jan 31) balance -100; statement 2 (through Feb 28) balance -250.
    # a purchase dated Jan 30 arrives with run 2: run 1 covered its date and missed it
    records = [rec(1, D(2026, 1, 31), -100, D(2026, 1, 31)), rec(2, D(2026, 2, 28), -250, D(2026, 2, 28))]
    moves = [
        mv(D(2026, 1, 10), -100, D(2026, 1, 31)),
        mv(D(2026, 1, 30), -50, D(2026, 2, 28), missed=True),
        mv(D(2026, 2, 10), -100, D(2026, 2, 28)),
    ]
    assert gaps(records, moves) == [(0, 1), (0, 0)]


def test_late_posting_at_the_anchor_leaves_no_lasting_difference() -> None:
    records = [rec(1, D(2026, 1, 31), -100, D(2026, 1, 31)), rec(2, D(2026, 2, 28), -150, D(2026, 2, 28))]
    moves = [mv(D(2026, 1, 30), -50, D(2026, 2, 28), missed=True)]
    assert gaps(records, moves) == [
        (-100, 1),
        (0, 0),
    ]  # opening -100, excludes the late row; then -50 explained


def test_backfill_uploaded_after_the_newer_one_is_order_independent() -> None:
    # the January run covers Jan 1..31; a row dated Jan 20 arrived with the February run
    records = [rec(3, D(2026, 1, 31), -100, D(2026, 1, 31)), rec(2, D(2026, 2, 28), -200, D(2026, 2, 28))]
    moves = [mv(D(2026, 1, 20), -30, D(2026, 2, 28), missed=True)]
    assert gaps(records, moves) == [
        (-100, 1),
        (-70, 0),
    ]  # row late for the January record, counted by February's


def test_a_movement_no_run_missed_counts_even_when_it_arrived_later() -> None:
    # delivered by a long CSV (through Mar 31) and by a FinTS run (through Feb 28): it arrived Feb 28, no run
    # covering its date ended before that
    records = [rec(2, D(2026, 2, 28), -100, D(2026, 2, 28))]
    assert gaps(records, [mv(D(2026, 2, 10), -100, D(2026, 2, 28))]) == [(0, 0)]
    # a row arriving on or before the record's coverage end is never late, whatever was missed
    assert gaps(records, [mv(D(2026, 2, 10), -100, D(2026, 2, 28), missed=True)]) == [(0, 0)]
    assert gaps(records, [mv(D(2026, 2, 10), -100)]) == [(0, 0)]  # no run delivered it


def test_gap_fill_spanning_a_record_leaves_a_cancelling_pair() -> None:
    # the bank's balance at Jan 31 includes a Jan 15 row that run 1 (Jan 1..31) did not deliver; a gap-fill
    # file arriving with coverage through Feb 28 delivers it afterwards: late for record 1, counted by 2
    records = [
        rec(0, D(2025, 12, 31), 0),
        rec(1, D(2026, 1, 31), -50, D(2026, 1, 31)),
        rec(2, D(2026, 2, 28), -50, D(2026, 2, 28)),
    ]
    assert gaps(records, [mv(D(2026, 1, 15), -50, D(2026, 2, 28), missed=True)]) == [
        (0, 0),
        (-50, 1),
        (50, 0),
    ]
    # a file reaching beyond record 2 makes the row late for it as well: no pair (D256)
    assert gaps(records, [mv(D(2026, 1, 15), -50, D(2026, 3, 31), missed=True)]) == [(0, 0), (-50, 1), (0, 1)]
    # where run 1 starts after the row's date nobody missed it: counted, no pair
    assert gaps(records, [mv(D(2026, 1, 15), -50, D(2026, 3, 31))]) == [(0, 0), (0, 0), (0, 0)]


def test_manual_record_without_coverage_and_user_entered_movements_count_everything() -> None:
    moves = [mv(D(2026, 1, 15), -50, D(2026, 3, 31), missed=True), mv(D(2026, 1, 16), -20)]
    assert gaps([rec(1, D(2026, 1, 31), -70)], moves) == [(0, 0)]  # manual, or a run without coverage
    covered = rec(1, D(2026, 1, 31), -70, D(2026, 1, 31))
    assert gaps([covered], moves) == [(-50, 1)]  # the user-entered -20 is never late: opening -70 + 20


def test_a_missing_row_leaves_a_lasting_difference_and_a_duplicated_row_too() -> None:
    records = [rec(1, D(2026, 1, 31), 0, D(2026, 1, 31)), rec(2, D(2026, 2, 28), -100, D(2026, 2, 28))]
    missing = [mv(D(2026, 2, 5), -60, D(2026, 2, 28))]  # the bank saw -100, the rows say -60
    assert gaps(records, missing) == [(0, 0), (-40, 0)]
    duplicated = [mv(D(2026, 2, 5), -100, D(2026, 2, 28)), mv(D(2026, 2, 5), -100, D(2026, 2, 28))]
    assert gaps(records, duplicated) == [(0, 0), (100, 0)]


def test_a_refund_booked_months_later_is_late_for_every_record_taken_before_it_arrived() -> None:
    # runs: Jan 1..Feb 3, Feb 4..Mar 3, Mar 4..Apr 2, Apr 3..Apr 30; two movements dated Jan 23 and Feb 9
    # arrive with the April 30 run, which the bank had not booked them in earlier
    records = [
        rec(1, D(2026, 2, 3), -100, D(2026, 2, 3)),
        rec(2, D(2026, 3, 3), -100, D(2026, 3, 3)),
        rec(3, D(2026, 4, 2), -100, D(2026, 4, 2)),
        rec(4, D(2026, 4, 30), -150, D(2026, 4, 30)),
    ]
    moves = [
        mv(D(2026, 1, 10), -100, D(2026, 2, 3)),
        mv(D(2026, 1, 23), -30, D(2026, 4, 30), missed=True),
        mv(D(2026, 2, 9), -20, D(2026, 4, 30), missed=True),
    ]
    assert gaps(records, moves) == [(0, 1), (0, 2), (0, 2), (0, 0)]


def test_a_late_arrival_is_named_by_the_latest_record_it_is_late_for() -> None:
    # the chain case: Jan 23 and Feb 9 arrive with the Apr 30 run, so they are late for the records of
    # Feb 3 (Jan 23 only), Mar 3 and Apr 2; the latest is Apr 2. A movement that was never late has none.
    records = [
        rec(1, D(2026, 2, 3), -100, D(2026, 2, 3)),
        rec(2, D(2026, 3, 3), -100, D(2026, 3, 3)),
        rec(3, D(2026, 4, 2), -100, D(2026, 4, 2)),
        rec(4, D(2026, 4, 30), -150, D(2026, 4, 30)),
    ]
    moves = [
        mv(D(2026, 1, 10), -100, D(2026, 2, 3), mid=10),
        mv(D(2026, 1, 23), -30, D(2026, 4, 30), missed=True, mid=11),
        mv(D(2026, 2, 9), -20, D(2026, 4, 30), missed=True, mid=12),
    ]
    found, late_for = record_gaps_with_late_for(DerivationInput(tuple(records), tuple(moves)))
    assert late_for == {11: D(2026, 4, 2), 12: D(2026, 4, 2)}
    assert [g.late_arrivals for g in found] == [1, 2, 2, 0]  # the count agrees with the mapping


def test_a_run_nested_in_a_longer_one_does_not_count_what_the_longer_one_missed() -> None:
    # run A covers Feb 1..Apr 30 (record Apr 30), run B covers March (record Mar 31); a row dated Feb 15
    # arrives with a May run: both runs missed it
    inner = rec(1, D(2026, 3, 31), -40, D(2026, 3, 31))
    outer = rec(2, D(2026, 4, 30), -40, D(2026, 4, 30))
    moves = [mv(D(2026, 3, 10), -40, D(2026, 3, 31)), mv(D(2026, 2, 15), -25, D(2026, 5, 31), missed=True)]
    assert gaps([inner, outer], moves) == [(0, 1), (0, 1)]  # B's record is the anchor
    earlier = rec(0, D(2026, 1, 31), 0)  # a manual record before them
    assert gaps([earlier, inner, outer], moves) == [(0, 0), (0, 1), (0, 1)]


def test_a_long_run_next_to_a_short_one_does_not_make_its_older_rows_late() -> None:
    # one run Jan 1..Dec 31 (record Dec 31) and a March run (record Mar 31): January's rows arrived Dec 31,
    # and the March run, starting in March, never covered January
    records = [rec(1, D(2026, 3, 31), -30, D(2026, 3, 31)), rec(2, D(2026, 12, 31), -30, D(2026, 12, 31))]
    moves = [mv(D(2026, 1, 10), -10, D(2026, 12, 31)), mv(D(2026, 3, 10), -20, D(2026, 3, 31))]
    assert gaps(records, moves) == [(0, 0), (0, 0)]


# ---- through the database --------------------------------------------------------------------


def test_the_database_inputs_carry_arrival_and_missed(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    csv = make_run(db_conn, s.account, covered_from=day(1, 1), covered_through=day(3, 31))
    fints = make_run(db_conn, s.account, covered_from=day(2, 1), covered_through=day(2, 28))
    original = make_source(db_conn, s.account, amount=-100, booked_on=day(2, 10), run_id=csv)
    make_entry(db_conn, original)
    make_source(db_conn, s.account, amount=-100, booked_on=day(2, 10), run_id=fints, duplicate_of=original)
    make_source(db_conn, s.account, amount=-5, booked_on=day(2, 11), importer=None)
    # delivered by the long run only, dated inside the short run's coverage: the short run missed it
    make_entry(db_conn, make_source(db_conn, s.account, amount=-7, booked_on=day(2, 12), run_id=csv))
    make_balance_record(db_conn, s.account, balance_on=day(2, 28), balance=-100, run_id=fints)
    data = load_derivation_input(db_conn, s.account)
    assert sorted((m.amount, m.arrived, m.missed) for m in data.movements) == [
        (-100, day(2, 28), False),
        (-7, day(3, 31), True),
        (-5, None, False),
    ]
    assert [(r.covered_through) for r in data.records] == [day(2, 28)]


def test_an_earlier_delivery_counts_as_an_arrival(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    long = make_run(db_conn, s.account, covered_from=day(1, 1), covered_through=day(12, 31))
    march = make_run(db_conn, s.account, covered_from=day(3, 1), covered_through=day(3, 31))
    jan = make_source(db_conn, s.account, amount=-10, booked_on=day(1, 10), run_id=long)
    make_entry(db_conn, jan)
    skipped = make_source(db_conn, s.account, amount=-20, booked_on=day(3, 10), run_id=long)
    make_entry(db_conn, skipped)
    db_conn.execute(
        text(
            "INSERT INTO source_transaction_earlier_delivery (source_transaction_id, import_run_id)"
            " VALUES (:s, :r)"
        ),
        {"s": skipped, "r": march},
    )
    data = load_derivation_input(db_conn, s.account)
    assert sorted((m.amount, m.arrived, m.missed) for m in data.movements) == [
        (-20, day(3, 31), False),  # the March run's skipped delivery is the earliest arrival
        (-10, day(12, 31), False),  # the March run never covered January
    ]


def test_a_card_late_posting_is_in_the_statement_and_the_entries_agree(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    run1 = make_run(db_conn, s.account, covered_from=day(1, 1), covered_through=day(1, 31))
    run2 = make_run(db_conn, s.account, covered_from=day(2, 1), covered_through=day(2, 28))
    early = make_source(db_conn, s.account, amount=-100, booked_on=day(1, 10), run_id=run1)
    make_entry(db_conn, early)
    late = make_source(db_conn, s.account, amount=-50, booked_on=day(1, 30), run_id=run2)
    make_entry(db_conn, late)
    make_entry(db_conn, make_source(db_conn, s.account, amount=-10, booked_on=day(2, 10), run_id=run2))
    dup = make_source(db_conn, s.account, amount=-50, booked_on=day(1, 30), run_id=run2, duplicate_of=late)
    first = make_balance_record(db_conn, s.account, balance_on=day(1, 31), balance=-100, run_id=run1)
    second = make_balance_record(db_conn, s.account, balance_on=day(2, 28), balance=-160, run_id=run2)
    s.recompute()
    items = {i.id: i for i in get_statement(db_conn, s.account).items if isinstance(i, RecordItem)}
    assert (items[first].difference, items[first].late_arrivals) == (0, 1)  # the opening, without the -50
    assert (items[second].difference, items[second].late_arrivals) == (0, 0)
    assert s.derived_of(first) is None
    assert s.derived_of(second) is None
    sources = {i.id: i for i in get_statement(db_conn, s.account).items if isinstance(i, SourceItem)}
    got = (sources[late].late_for, sources[early].late_for, sources[dup].late_for)
    assert got == (day(1, 31), None, None)
    s.check()
