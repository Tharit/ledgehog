"""The unexplained difference, the records that localise it, and anchoring (spec §3.11, §5.10)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection

from app.core.balance.difference import is_anchored, records_since_zero, unexplained_difference
from tests.core.balance.scene import Scene, day

Make = Callable[..., int]


def _diff(s: Scene) -> int | None:
    s.recompute()
    return unexplained_difference(s.conn, s.account)


def test_a_back_dated_booking_leaves_opposite_reconciliations_that_cancel(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    r1 = s.reported(day(2, 1), 1000)
    r2 = s.reported(day(3, 1), 900)
    s.move(day(1, 20), -100)  # the bank booked it into a day it had already closed
    assert _diff(s) is None
    assert s.derived_of(r1) == ("reconciliation", day(2, 1), 100)
    assert s.derived_of(r2) == ("reconciliation", day(3, 1), -100)
    assert records_since_zero(db_conn, s.account) == []
    s.check()


def test_a_missing_row_leaves_a_persistent_difference_localised_by_the_reported_records(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.reported(day(2, 1), 1000)
    r2 = s.reported(day(3, 1), 800)
    r3 = s.reported(day(4, 1), 800)
    assert _diff(s) == -200
    assert records_since_zero(db_conn, s.account) == [r2, r3]
    s.check()


def test_the_difference_is_the_sum_and_the_since_zero_list_starts_where_it_was_last_zero(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.reported(day(1, 1), 1000)  # the anchor
    s.reported(day(2, 1), 1000)  # 0
    r2 = s.reported(day(3, 1), 800)  # -200
    r3 = s.reported(day(4, 1), 800)  # 0, the sum stays -200
    r4 = s.reported(day(5, 1), 700)  # -100
    assert _diff(s) == -300
    assert records_since_zero(db_conn, s.account) == [r2, r3, r4]


def test_a_manual_record_between_two_reported_ones_cancels(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.reported(day(2, 1), 1000)
    manual = s.manual(day(2, 15), 1500)  # a wrong count
    s.reported(day(3, 1), 1000)
    assert _diff(s) is None
    assert s.derived_of(manual) == ("reconciliation", day(2, 15), 500)
    assert records_since_zero(db_conn, s.account) == []
    s.check()


def test_the_sum_starts_at_the_first_reported_record(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.manual(day(1, 15), 1200)  # +200 before any reported record: not part of the sum
    s.reported(day(2, 1), 1300)  # +100
    assert _diff(s) == 100


def test_a_manual_anchor_meeting_its_first_reported_record_shows_a_difference(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.move(day(1, 20), -100)
    r = s.reported(day(2, 1), 800)
    assert _diff(s) == -100
    assert records_since_zero(db_conn, s.account) == [r]


def test_a_reported_anchor_explains_nothing_so_it_is_no_difference(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    s.reported(day(1, 1), 1000)
    assert _diff(s) is None
    assert records_since_zero(db_conn, s.account) == []


def test_fixing_the_cause_removes_the_difference(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    s.manual(day(1, 1), 1000)
    s.reported(day(2, 1), 1000)
    s.reported(day(3, 1), 800)
    assert _diff(s) == -200
    s.move(day(2, 20), -200)  # the missing row is imported
    assert _diff(s) is None
    assert records_since_zero(db_conn, s.account) == []
    s.check()


def test_a_depot_never_has_an_unexplained_difference(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account, kind="depot")
    s.reported(day(1, 1), 1000)
    s.reported(day(2, 1), 1500)
    s.reported(day(3, 1), 900)
    assert _diff(s) is None
    assert records_since_zero(db_conn, s.account) == []


def test_an_account_without_records_has_no_difference(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account)
    assert _diff(s) is None
    assert records_since_zero(db_conn, s.account) == []


def test_an_account_with_entries_and_no_record_is_not_anchored(
    db_conn: Connection, make_account: Make
) -> None:
    s = Scene(db_conn, make_account)
    assert is_anchored(db_conn, s.account)  # nothing to anchor
    s.move(day(1, 10), -100)
    s.recompute()
    assert s.derived() == []
    assert not is_anchored(db_conn, s.account)
    s.manual(day(1, 1), 500)
    assert is_anchored(db_conn, s.account)
