"""The account statement (architecture §4.1 'The account statement'): order, paging and the gap of
each record, which come from the rule that derives the entries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Connection, text

from app.core.balance.derived import CountingRecord, DerivationInput, Movement, record_gaps
from app.core.balance.statement import RecordItem, SourceItem, StatementAccountMissing, get_statement
from tests.core.balance.scene import Scene, day
from tests.invariants.helpers import make_entry, make_run, make_source

Make = Callable[..., int]


def full(conn: Connection, account: int) -> list[SourceItem | RecordItem]:
    return list(get_statement(conn, account, limit=500).items)


def ledger_balance(conn: Connection, account: int) -> int:
    return int(
        conn.execute(
            text("SELECT COALESCE(sum(amount), 0) FROM ledger_entry WHERE account_id = :a"), {"a": account}
        ).scalar_one()
    )


def assert_agrees_with_the_ledger(s: Scene, late: int = 0) -> None:
    """The newest counting record's balance plus the non-duplicate movements dated after it (all of them
    with no record) plus `late`, the amounts of the late arrivals for it, is the account's balance; every
    record's difference is its derived entry's amount (the anchor's, its opening)."""
    s.recompute()
    items = full(s.conn, s.account)
    records = [i for i in items if isinstance(i, RecordItem)]
    newest = records[0] if records else None  # the statement is newest first
    after = [
        i.amount
        for i in items
        if isinstance(i, SourceItem)
        and i.duplicate_of is None
        and (newest is None or i.booked_on > newest.balance_on)
    ]
    assert (newest.balance if newest else 0) + sum(after) + late == ledger_balance(s.conn, s.account)
    for item in items:
        if isinstance(item, RecordItem):
            owned = s.derived_of(item.id)
            assert item.difference == (0 if owned is None else owned[2])
    s.check()


# ---- the newest record plus what follows it is the ledger balance ----------------


def test_no_records_counts_from_zero(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 1), 1000)
    s.move(day(1, 5), -300)
    items = full(db_conn, s.account)
    assert [i.booked_on for i in items if isinstance(i, SourceItem)] == [day(1, 5), day(1, 1)]
    assert not any(isinstance(i, RecordItem) for i in items)
    assert_agrees_with_the_ledger(s)


def test_an_empty_account_has_an_empty_statement(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    got = get_statement(db_conn, s.account)
    assert (got.items, got.total) == ((), 0)


def test_anchor_only_counts_what_precedes_the_anchor_back_from_it(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 1), -100)
    s.move(day(1, 2), -50)
    s.manual(day(1, 2), 1000)  # the anchor ends its day: both rows are in its interval
    s.move(day(1, 3), 20)  # after it
    items = full(db_conn, s.account)
    (anchor,) = (i for i in items if isinstance(i, RecordItem))
    assert (anchor.anchor, anchor.difference, anchor.balance, anchor.late_arrivals) == (True, 1150, 1000, 0)
    assert_agrees_with_the_ledger(s)


def test_several_records_each_interval_counts_from_the_previous_record(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 31), 1000)
    s.move(day(2, 3), -100)
    s.move(day(2, 10), -50)
    s.manual(day(2, 28), 900)  # 1000 - 150 = 850 expected: a reconciliation of +50
    s.move(day(3, 5), -10)
    s.manual(day(3, 31), 890)  # 900 - 10: explained
    s.move(day(4, 2), 5)  # after the last record
    items = full(db_conn, s.account)
    records = [i for i in items if isinstance(i, RecordItem)]
    assert [(r.balance_on, r.difference) for r in reversed(records)] == [
        (day(1, 31), 1000),
        (day(2, 28), 50),
        (day(3, 31), 0),
    ]
    assert_agrees_with_the_ledger(s)


def test_records_sharing_a_date_stand_after_the_days_movements_and_the_later_one_owns_none(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 100)
    s.move(day(1, 5), -10)
    first = s.reported(day(1, 5), 85)
    second = s.manual(day(1, 5), 80)
    items = full(db_conn, s.account)
    ids = [("record", i.id) if isinstance(i, RecordItem) else ("source", i.id) for i in items]
    assert ids[0] == ("record", second) and ids[1] == ("record", first)  # by id, descending, above the row
    rec = {i.id: i for i in items if isinstance(i, RecordItem)}
    assert rec[first].difference == -5
    assert rec[second].difference == -5  # the change between the two
    assert_agrees_with_the_ledger(s)


def test_a_reverted_runs_record_does_not_count_and_is_not_an_item(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.move(day(1, 5), -10)
    kept = s.manual(day(1, 6), 500)
    gone_run = make_run(db_conn, s.account, status="reverted")
    s.reported(day(1, 20), 12345, run_id=gone_run)
    items = full(db_conn, s.account)
    assert [i.id for i in items if isinstance(i, RecordItem)] == [kept]
    assert get_statement(db_conn, s.account).total == 2
    assert_agrees_with_the_ledger(s)


def test_duplicates_are_listed_with_what_they_duplicate_and_move_nothing(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    original = make_source(db_conn, s.account, amount=-40, booked_on=day(1, 3))
    make_entry(db_conn, original)
    dup = make_source(db_conn, s.account, amount=-40, booked_on=day(1, 4), duplicate_of=original)
    s.move(day(1, 6), -10)
    items = full(db_conn, s.account)
    (dup_item,) = (i for i in items if i.id == dup and isinstance(i, SourceItem))
    assert dup_item.entry_id is None
    assert dup_item.duplicate_of is not None
    assert (dup_item.duplicate_of.id, dup_item.duplicate_of.booked_on, dup_item.duplicate_of.amount) == (
        original,
        day(1, 3),
        -40,
    )
    assert get_statement(db_conn, s.account).total == 4
    assert_agrees_with_the_ledger(s)


def test_a_duplicate_as_the_newest_item_does_not_break_the_agreement(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 100)
    original = make_source(db_conn, s.account, amount=-5, booked_on=day(1, 2))
    make_entry(db_conn, original)
    make_source(db_conn, s.account, amount=-5, booked_on=day(1, 9), duplicate_of=original)
    assert isinstance(full(db_conn, s.account)[0], SourceItem)
    assert_agrees_with_the_ledger(s)


def test_an_investment_account_has_valuations_as_differences(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    s.manual(day(1, 1), 5_000_000)
    s.manual(day(2, 1), 5_400_000)
    s.move(day(2, 15), -1000)
    items = full(db_conn, s.account)
    records = [i for i in items if isinstance(i, RecordItem)]
    assert [r.difference for r in reversed(records)] == [5_000_000, 400_000]
    assert_agrees_with_the_ledger(s)
    assert s.derived()[-1][0] == "valuation"


def test_an_account_kept_by_records_alone_has_only_record_items(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    s.manual(day(1, 1), 100)
    s.manual(day(2, 1), 150)
    assert {type(i) for i in full(db_conn, s.account)} == {RecordItem}
    assert_agrees_with_the_ledger(s)


def test_backfill_before_the_anchor_counts_back_from_the_anchor(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(3, 1), 1000)
    s.move(day(2, 1), -300)  # a backfilled row older than the anchor
    s.move(day(2, 10), 100)
    s.move(day(3, 5), -50)
    assert [i.booked_on for i in full(db_conn, s.account) if isinstance(i, SourceItem)] == [
        day(3, 5),
        day(2, 10),
        day(2, 1),
    ]
    assert_agrees_with_the_ledger(s)


# ---- the gap is the derivation's own ---------------------------------------------------------


def test_record_gaps_is_the_formula_of_the_derived_entries() -> None:
    data = DerivationInput(
        (
            CountingRecord(1, date(2026, 1, 31), 1000),
            CountingRecord(2, date(2026, 2, 28), 900),
        ),
        (
            Movement(date(2026, 1, 10), -20),
            Movement(date(2026, 2, 3), -100),
            Movement(date(2026, 2, 3), -50),
        ),
        {},
    )
    assert [(g.anchor, g.amount, g.late_arrivals) for g in record_gaps(data)] == [
        (True, 1020, 0),
        (False, 50, 0),
    ]


# ---- order, paging, the amount filter --------------------------------------------------------


def test_paging_slices_one_total_order_and_total_counts_everything(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 0)
    for d in range(2, 8):
        s.move(day(1, d), -d)
    everything = full(db_conn, s.account)
    assert len(everything) == 7
    seen: list[tuple[str, int]] = []
    for offset in (0, 3, 6):
        page = get_statement(db_conn, s.account, limit=3, offset=offset)
        assert (page.total, page.limit, page.offset) == (7, 3, offset)
        seen += [(i.kind, i.id) for i in page.items]
    assert seen == [(i.kind, i.id) for i in everything]


def test_same_date_rows_are_ordered_by_id_descending(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    a = make_source(db_conn, s.account, amount=-1, booked_on=day(1, 1))
    b = make_source(db_conn, s.account, amount=-2, booked_on=day(1, 1))
    make_entry(db_conn, a)
    make_entry(db_conn, b)
    items = full(db_conn, s.account)
    assert [i.id for i in items] == [b, a]


def test_the_amount_filter_keeps_imported_non_duplicate_rows_of_that_amount_and_no_record(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 100)
    hit = make_source(db_conn, s.account, amount=-7, booked_on=day(1, 2))
    make_entry(db_conn, hit)
    other = make_source(db_conn, s.account, amount=-8, booked_on=day(1, 3))
    make_entry(db_conn, other)
    authored = make_source(db_conn, s.account, amount=-7, booked_on=day(1, 4), importer=None)
    make_entry(db_conn, authored)
    make_source(db_conn, s.account, amount=-7, booked_on=day(1, 5), duplicate_of=hit)
    later = make_source(db_conn, s.account, amount=-7, booked_on=day(1, 6))
    make_entry(db_conn, later)
    got = get_statement(db_conn, s.account, amount=-7)
    assert [i.id for i in got.items] == [later, hit] and got.total == 2
    assert all(isinstance(i, SourceItem) for i in got.items)
    page = get_statement(db_conn, s.account, amount=-7, limit=1, offset=1)
    assert [i.id for i in page.items] == [hit] and page.total == 2


def test_items_carry_entry_run_and_authored(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    imported = make_source(db_conn, s.account, amount=-5, booked_on=day(1, 1), purpose="Coffee")
    first = make_entry(db_conn, imported, amount=-2)
    make_entry(db_conn, imported, amount=-3)
    by_hand = make_source(db_conn, s.account, amount=9, booked_on=day(1, 2), importer=None)
    make_entry(db_conn, by_hand)
    items = {i.id: i for i in full(db_conn, s.account) if isinstance(i, SourceItem)}
    assert (items[imported].entry_id, items[imported].authored, items[imported].purpose) == (
        first,
        False,
        "Coffee",
    )
    assert items[imported].run_id is not None
    assert (items[by_hand].authored, items[by_hand].run_id) == (True, None)


def test_a_missing_account_is_refused(db_conn: Connection) -> None:
    with pytest.raises(StatementAccountMissing):
        get_statement(db_conn, 999_999)
