"""The pending section cut by counterparty (`ux/views/review-queue.md`, D273): groups by the anchor source's
normalised counterparty name, ordered by count then key with "Other" last; paging across band boundaries."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.units.read import InvalidCursor, review_queue
from tests.core.units.helpers import Bench
from tests.invariants.helpers import make_source

DAY = date(2026, 3, 10)


@pytest.fixture
def bench(db_conn: Connection, make_account: Any) -> Bench:
    return Bench(db_conn, make_account)


def _unit(bench: Bench, name: str | None, *, day: int = 1, account: int | None = None) -> int:
    """A pending unit (one uncategorised flow) whose source names `name` as counterparty."""
    src = make_source(
        bench.conn,
        account or bench.a,
        booked_on=date(2026, 3, day),
        amount=-100,
        columns={"counterparty_name": name},
    )
    bench._each[src] = -100
    return bench.flow(src, done=False)


def _pending(db_conn: Connection, **kw: Any) -> Any:
    return review_queue(db_conn, cut="counterparty", **kw).sections[0]


def _groups(section: Any) -> list[tuple[str | None, int, bool]]:
    return [(g.label, g.count, g.other) for g in section.counterparty_groups]


def test_groups_are_ordered_by_count_then_name_with_other_last(db_conn: Connection, bench: Bench) -> None:
    rewe = [_unit(bench, "REWE", day=d) for d in (1, 2, 3)]
    aldi = [_unit(bench, "Aldi", day=d) for d in (4, 5)]
    lidl = [_unit(bench, "Lidl", day=d) for d in (6, 7)]
    solo = _unit(bench, "Solo", day=8)
    none = _unit(bench, None, day=9)
    s = _pending(db_conn)
    assert _groups(s) == [("REWE", 3, False), ("Aldi", 2, False), ("Lidl", 2, False), (None, 2, True)]
    assert [u.anchor_entry_id for u in s.units] == [*rewe, *aldi, *lidl, solo, none]
    assert s.total == 9 and s.next_cursor is None
    assert [u.counterparty_key for u in s.units] == ["rewe"] * 3 + ["aldi"] * 2 + ["lidl"] * 2 + [None] * 2


def test_grouping_ignores_case_and_repeated_spaces_and_is_labelled_by_the_first_unit(
    db_conn: Connection, bench: Bench
) -> None:
    late = _unit(bench, "rewe  markt", day=9)
    first = _unit(bench, "  REWE Markt ", day=2)
    mid = _unit(bench, "Rewe\tMarkt", day=5)
    s = _pending(db_conn)
    assert _groups(s) == [("  REWE Markt ", 3, False)]
    assert [u.anchor_entry_id for u in s.units] == [first, mid, late]
    assert s.counterparty_groups[0].key == "rewe markt"


def test_blank_names_and_singletons_go_to_other(db_conn: Connection, bench: Bench) -> None:
    _unit(bench, "   ", day=1)
    _unit(bench, "", day=2)
    _unit(bench, None, day=3)
    _unit(bench, "One", day=4)
    s = _pending(db_conn)
    assert _groups(s) == [(None, 4, True)]


def test_the_account_filter_narrows_the_counts(db_conn: Connection, bench: Bench) -> None:
    for d in (1, 2):
        _unit(bench, "REWE", day=d)
    _unit(bench, "REWE", day=3, account=bench.b)
    for d in (4, 5):
        _unit(bench, "Aldi", day=d, account=bench.b)
    assert _groups(_pending(db_conn)) == [("REWE", 3, False), ("Aldi", 2, False)]
    assert _groups(_pending(db_conn, account_ids=(bench.a,))) == [("REWE", 2, False)]
    assert _groups(_pending(db_conn, account_ids=(bench.b,))) == [("Aldi", 2, False), (None, 1, True)]


def test_paging_continues_bands_with_no_gap_or_duplicate(db_conn: Connection, bench: Bench) -> None:
    expected: list[int] = []
    expected += [_unit(bench, "REWE", day=d) for d in (1, 2, 3, 4)]
    expected += [_unit(bench, "Aldi", day=d) for d in (5, 6, 7)]
    expected += [_unit(bench, "Lidl", day=d) for d in (8, 9, 10)]
    expected += [_unit(bench, "Solo", day=11), _unit(bench, None, day=12)]
    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        q = review_queue(
            db_conn,
            cut="counterparty",
            limit=3,
            section=None if cursor is None else "pending_review",
            cursor=cursor,
        )
        s = q.sections[0]
        assert s.total == 12
        assert [(g.count) for g in s.counterparty_groups] == [4, 3, 3, 2]  # whole section on every page
        seen += [u.anchor_entry_id for u in s.units]
        pages += 1
        cursor = s.next_cursor
        if cursor is None:
            break
    assert seen == expected and pages == 4


def test_the_other_cuts_and_the_date_cut_are_unchanged(db_conn: Connection, bench: Bench) -> None:
    a = _unit(bench, "REWE", day=9)
    b = _unit(bench, "REWE", day=2)
    c = _unit(bench, "Aldi", day=5)
    by_date = review_queue(db_conn)
    assert [u.anchor_entry_id for u in by_date.sections[0].units] == [b, c, a]
    assert by_date.sections[0].counterparty_groups == ()
    assert all(u.counterparty_key is None for u in by_date.sections[0].units)
    assert review_queue(db_conn, cut="date") == by_date
    cp = review_queue(db_conn, cut="counterparty")
    assert [s.kind for s in cp.sections] == ["pending_review", "needs_account", "waiting"]
    assert cp.sections[1].counterparty_groups == () and cp.sections[2].counterparty_groups == ()


def test_a_cursor_of_one_cut_is_not_valid_for_the_other(db_conn: Connection, bench: Bench) -> None:
    for d in (1, 2, 3):
        _unit(bench, "REWE", day=d)
    by_date = review_queue(db_conn, limit=1).sections[0].next_cursor
    by_cp = review_queue(db_conn, limit=1, cut="counterparty").sections[0].next_cursor
    assert by_date and by_cp
    with pytest.raises(InvalidCursor):
        review_queue(db_conn, section="pending_review", cursor=by_date, cut="counterparty")
    with pytest.raises(InvalidCursor):
        review_queue(db_conn, section="pending_review", cursor=by_cp)


def _confirm(bench: Bench, anchors: list[int]) -> None:
    """Commit units: the entries get their category, so the units leave the pending section."""
    bench.conn.execute(
        text("UPDATE ledger_entry SET category_id = :c WHERE id = ANY(:ids)"),
        {"c": bench.cat, "ids": anchors},
    )


def _next(db_conn: Connection, cursor: str, limit: int) -> Any:
    return review_queue(
        db_conn, cut="counterparty", limit=limit, section="pending_review", cursor=cursor
    ).sections[0]


def test_commits_between_pages_do_not_split_the_band_the_cursor_is_in(
    db_conn: Connection, bench: Bench
) -> None:
    a = [_unit(bench, "A", day=d) for d in range(1, 13)]  # 12
    b = [_unit(bench, "B", day=d) for d in range(1, 12)]  # 11
    c = [_unit(bench, "C", day=d) for d in range(1, 11)]  # 10
    s1 = _pending(db_conn, limit=4)
    assert [u.anchor_entry_id for u in s1.units] == a[:4] and s1.next_cursor
    _confirm(bench, a[4:7])  # A: 12 -> 9, now below B and C
    s2 = _next(db_conn, s1.next_cursor, 20)
    # the rest of A first, then B and C in their order; nothing skipped, A is not split
    assert [u.anchor_entry_id for u in s2.units] == [*a[7:], *b, *c[:4]] and s2.next_cursor
    assert [u.counterparty_key for u in s2.units] == ["a"] * 5 + ["b"] * 11 + ["c"] * 4
    s3 = _next(db_conn, s2.next_cursor, 20)
    # C's tail; then A, whose count dropped below C's after it was passed, comes up again: every unit of it is
    # already held by the client, which de-duplicates by unit
    got = [u.anchor_entry_id for u in s3.units]
    assert got[:6] == c[4:] and s3.next_cursor is None
    assert set(got[6:]) == {*a[:4], *a[7:]} and set(got[6:]) <= {*a, *b, *c}


def test_a_group_shrinking_to_one_after_it_was_passed_does_not_break_paging(
    db_conn: Connection, bench: Bench
) -> None:
    a = [_unit(bench, "A", day=d) for d in (1, 2, 3)]
    b = [_unit(bench, "B", day=d) for d in (4, 5)]
    s1 = _pending(db_conn, limit=2)
    assert [u.anchor_entry_id for u in s1.units] == a[:2] and s1.next_cursor
    _confirm(bench, a[:2])  # A: 3 -> 1, it is Other now
    _confirm(bench, [b[0]])  # B: 2 -> 1, Other too
    s2 = _next(db_conn, s1.next_cursor, 5)
    assert [u.anchor_entry_id for u in s2.units] == [a[2], b[1]]
    assert s2.next_cursor is None
    assert [g.other for g in s2.counterparty_groups] == [True]
