"""Reading units as stored: one unit, and the review queue (sections, order, cursor, new-count)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.units.read import (
    InvalidCursor,
    decode_cursor,
    encode_cursor,
    get_unit,
    new_unit_count,
    review_queue,
)
from tests.core.units.helpers import Bench, D, keys
from tests.fixtures import ledger_seed as seed


@pytest.fixture
def bench(db_conn: Connection, make_account: Any) -> Bench:
    return Bench(db_conn, make_account)


# ---- get_unit -----------------------------------------------------------------------------------


def test_a_split_is_one_unit_from_any_of_its_entries(db_conn: Connection, bench: Bench) -> None:
    src = bench.source()
    one, two = bench.flow(src), bench.flow(src, done=False)
    for start in (one, two):
        unit = get_unit(db_conn, start)
        assert unit is not None
        assert (unit.anchor_entry_id, unit.unit_key) == (one, src)
        assert [e.id for e in unit.entries] == [one, two]
        assert not unit.state.confirmed and unit.state.reasons == ("incomplete",)


def test_a_pair_is_one_unit_with_both_sources(db_conn: Connection, bench: Bench) -> None:
    s1, s2 = bench.source(), bench.source(bench.b)
    x, y = bench.transfer(s1), bench.transfer(s2)
    sib = bench.flow(s2)
    bench.pair(x, y)
    for start in (x, y, sib):
        unit = get_unit(db_conn, start)
        assert unit is not None and unit.unit_key == s1 and unit.anchor_entry_id == x
        assert [e.id for e in unit.entries] == [x, y, sib]
        assert unit.state.confirmed
    assert unit.entries[0].partner is not None and unit.entries[0].partner.entry_id == y


def test_a_confirmed_unit_has_no_reasons_and_a_proposal_names_its_reason(
    db_conn: Connection, bench: Bench
) -> None:
    ok = bench.flow(bench.source(), derivation=keys(category="rule"))
    held = bench.flow(bench.source(), derivation=keys(category="history"))
    a, b = get_unit(db_conn, ok), get_unit(db_conn, held)
    assert a is not None and a.state.confirmed and a.state.reasons == ()
    assert b is not None and b.state.reasons == ("non_standing_keys",)
    assert b.entries[0].derivation == {"category": {"pass": "history"}}


def test_no_unit_for_a_missing_or_derived_entry(db_conn: Connection, bench: Bench) -> None:
    assert get_unit(db_conn, 987654) is None
    assert get_unit(db_conn, seed.derived(db_conn, bench.a)) is None


# ---- the queue ----------------------------------------------------------------------------------


def _anchors(queue: Any, kind: str = "pending_review") -> list[int]:
    (section,) = [s for s in queue.sections if s.kind == kind]
    return [u.anchor_entry_id for u in section.units]


def test_the_queue_has_three_sections_the_last_two_empty(db_conn: Connection, bench: Bench) -> None:
    q = review_queue(db_conn)
    assert [s.kind for s in q.sections] == ["pending_review", "needs_account", "waiting"]
    assert [s.total for s in q.sections] == [0, 0, 0] and q.total == 0
    bench.flow(bench.source(), done=False)
    q = review_queue(db_conn)
    assert [s.total for s in q.sections] == [1, 0, 0] and q.total == 1


def test_only_units_that_are_not_confirmed_are_listed_in_date_then_anchor_order(
    db_conn: Connection, bench: Bench
) -> None:
    late = bench.flow(bench.source(on=date(2026, 5, 1)), done=False)
    early = bench.flow(bench.source(on=date(2026, 1, 1)), done=False)
    same_day_2 = bench.flow(bench.source(on=date(2026, 3, 1)), done=False)
    same_day_1 = bench.flow(bench.source(on=date(2026, 3, 1)), derivation=keys(category="llm"))
    bench.flow(bench.source(on=date(2026, 2, 1)))  # confirmed: not listed
    seed.derived(db_conn, bench.a)  # derived: in no unit
    q = review_queue(db_conn)
    assert _anchors(q) == [early, same_day_2, same_day_1, late]  # ids ascend within a day
    assert same_day_2 < same_day_1


def test_a_unit_is_listed_once_with_all_its_entries_and_dated_by_its_anchor(
    db_conn: Connection, bench: Bench
) -> None:
    s1, s2 = bench.source(on=date(2026, 3, 5)), bench.source(bench.b, on=date(2026, 3, 1), amount=100)
    x = bench.transfer(s1)
    y = bench.transfer(s2, derivation=keys(counter_account="history"))
    sib = bench.flow(s1, done=False)
    bench.pair(x, y)
    q = review_queue(db_conn)
    assert q.total == 1
    (unit,) = q.sections[0].units
    assert (unit.anchor_entry_id, unit.unit_key) == (x, s1)
    assert [e.id for e in unit.entries] == [x, y, sib]
    assert unit.state.reasons == ("incomplete", "non_standing_keys")


def test_pages_follow_the_cursor_and_survive_changes_between_requests(
    db_conn: Connection, bench: Bench
) -> None:
    anchors = [bench.flow(bench.source(on=date(2026, 1, 1 + i)), done=False) for i in range(7)]
    first = review_queue(db_conn, limit=3)
    sec = first.sections[0]
    assert (sec.total, [u.anchor_entry_id for u in sec.units]) == (7, anchors[:3]) and sec.next_cursor
    # while the client is between pages: one listed unit is resolved, one new unit arrives before the cursor
    db_conn.execute(
        text("UPDATE ledger_entry SET type = 'flow', category_id = :c WHERE id = :i"),
        {"c": bench.cat, "i": anchors[1]},
    )
    arrived = bench.flow(bench.source(on=date(2026, 1, 1)), done=False)
    second = review_queue(db_conn, limit=3, section="pending_review", cursor=sec.next_cursor)
    assert [u.anchor_entry_id for u in second.sections[0].units] == anchors[3:6]
    assert second.sections[0].total == 7  # 7 - 1 resolved + 1 arrived
    third = review_queue(db_conn, limit=3, section="pending_review", cursor=second.sections[0].next_cursor)
    assert [u.anchor_entry_id for u in third.sections[0].units] == anchors[6:] and not third.sections[
        0
    ].next_cursor
    assert arrived not in _anchors(second) + _anchors(third)  # it sorts before the cursor: not shown


def test_a_cursor_past_the_end_is_an_empty_page_with_the_total(db_conn: Connection, bench: Bench) -> None:
    bench.flow(bench.source(on=date(2026, 1, 1)), done=False)
    q = review_queue(db_conn, section="pending_review", cursor=encode_cursor(date(2030, 1, 1), 1))
    assert q.sections[0].units == () and q.sections[0].total == 1 and q.total == 1


def test_a_single_other_section_still_reports_the_total(db_conn: Connection, bench: Bench) -> None:
    bench.flow(bench.source(), done=False)
    q = review_queue(db_conn, section="waiting")
    assert [s.kind for s in q.sections] == ["waiting"] and q.sections[0].total == 0 and q.total == 1


@pytest.mark.parametrize("token", ["", "!!", "Zm9v", encode_cursor(D, 1)[:-3]])
def test_a_foreign_cursor_is_refused(token: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(token)


def test_the_cursor_round_trips() -> None:
    assert decode_cursor(encode_cursor(D, 42)) == (D, 42)


def test_new_count_counts_units_whose_anchor_arrived_after_the_snapshot(
    db_conn: Connection, bench: Bench
) -> None:
    old_src = bench.source()
    old = bench.flow(old_src, done=False)
    snap = review_queue(db_conn).snapshot
    assert new_unit_count(db_conn, snap)[0] == 0
    bench.flow(bench.source(), done=False)  # a new unit
    bench.flow(bench.source())  # confirmed: not in the queue
    s = bench.source()
    bench.flow(s, done=False), bench.flow(s, done=False)  # one new unit of two entries
    bench.flow(old_src, done=False)  # an entry added to an OLD unit is not a new unit
    count, fresh = new_unit_count(db_conn, snap)
    assert count == 2 and fresh != snap
    assert new_unit_count(db_conn, fresh)[0] == 0
    assert old in _anchors(review_queue(db_conn))


def test_a_foreign_snapshot_is_refused(db_conn: Connection) -> None:
    with pytest.raises(InvalidCursor):
        new_unit_count(db_conn, "garbage")
