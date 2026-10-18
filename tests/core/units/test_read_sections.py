"""The review queue's three sections (spec §5.7, §6): `needs_account` and `waiting` split off
`pending_review`, disjoint, set-based; the per-currency groups; the unit's facts (the currency, the account
it waits for)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.units.read import actionable_count, review_queue
from tests.core.units.helpers import Bench
from tests.invariants.helpers import link_account, make_instance, make_run, make_source

DAY = date(2026, 3, 10)


@pytest.fixture
def bench(db_conn: Connection, make_account: Any) -> Bench:
    return Bench(db_conn, make_account)


def _leg(
    bench: Bench,
    *,
    on: date = DAY,
    instructed: str | None = "USD",
    account: int | None = None,
    currency: str = "EUR",
    **cols: Any,
) -> int:
    """An unpaired transfer leg, of a source with an instructed currency unless `instructed` is None."""
    src = make_source(
        bench.conn,
        account or bench.a,
        booked_on=on,
        amount=-100,
        currency=currency,
        columns={"instructed_currency": instructed, "instructed_amount": -110 if instructed else None},
    )
    bench._each[src] = -100
    return bench.transfer(src, **cols)


def _wait(conn: Connection, entry: int) -> None:
    conn.execute(text("UPDATE ledger_entry SET review_flags = ARRAY['waiting'] WHERE id = :i"), {"i": entry})


def _sections(queue: Any) -> dict[str, list[int]]:
    return {s.kind: [u.anchor_entry_id for u in s.units] for s in queue.sections}


def _sync(conn: Connection, account: int, through: date | None) -> None:
    instance = make_instance(conn)
    link_account(conn, account, instance)
    if through is not None:
        make_run(conn, account, covered_through=through, instance_id=instance)


def test_a_leg_with_an_instructed_currency_and_no_account_for_it_needs_an_account(
    db_conn: Connection, bench: Bench
) -> None:
    leg = _leg(bench)
    q = review_queue(db_conn)
    assert _sections(q) == {"pending_review": [], "needs_account": [leg], "waiting": []}
    assert [s.total for s in q.sections] == [0, 1, 0] and q.total == 1
    (unit,) = q.sections[1].units
    assert unit.needs_account == "USD" and unit.waiting is None


def test_a_leg_without_an_instructed_currency_stays_in_pending_review(
    db_conn: Connection, bench: Bench
) -> None:
    leg = _leg(bench, instructed=None)
    assert _sections(review_queue(db_conn)) == {"pending_review": [leg], "needs_account": [], "waiting": []}


def test_a_leg_with_a_counter_account_does_not_need_one(db_conn: Connection, bench: Bench) -> None:
    leg = _leg(bench, counter_account_id=bench.b)
    assert _sections(review_queue(db_conn))["needs_account"] == []
    assert leg in _sections(review_queue(db_conn))["pending_review"]


def test_an_open_account_in_the_currency_means_the_leg_does_not_need_one(
    db_conn: Connection, bench: Bench, make_account: Any
) -> None:
    leg = _leg(bench)
    make_account(db_conn, name="Cash USD", kind="cash", currency="USD")
    assert _sections(review_queue(db_conn)) == {"pending_review": [leg], "needs_account": [], "waiting": []}


def test_accounts_in_other_currencies_do_not_count(
    db_conn: Connection, bench: Bench, make_account: Any
) -> None:
    # the leg's own account cannot match: a source's instructed currency differs from its account's (CHECK)
    make_account(db_conn, name="Cash CHF", kind="cash", currency="CHF")
    leg = _leg(bench)
    assert _sections(review_queue(db_conn))["needs_account"] == [leg]


def test_a_closed_account_counts_only_for_dates_up_to_its_closing(
    db_conn: Connection, bench: Bench, make_account: Any
) -> None:
    usd = make_account(db_conn, name="Old cash", kind="cash", currency="USD")
    db_conn.execute(text("UPDATE account SET closed_on = :d WHERE id = :a"), {"d": DAY, "a": usd})
    on_closing_day = _leg(bench, on=DAY)
    after = _leg(bench, on=date(2026, 3, 11))
    sections = _sections(review_queue(db_conn))
    assert sections["needs_account"] == [after] and sections["pending_review"] == [on_closing_day]


def test_a_paired_leg_does_not_need_an_account(db_conn: Connection, bench: Bench) -> None:
    x = _leg(bench)
    y = bench.transfer(
        bench.source(bench.b, amount=100), derivation='{"counter_account": {"pass": "history"}}'
    )
    bench.pair(x, y)
    assert _sections(review_queue(db_conn))["needs_account"] == []


def test_a_waiting_leg_is_in_waiting_with_the_account_and_its_coverage(
    db_conn: Connection, bench: Bench
) -> None:
    _sync(db_conn, bench.b, date(2026, 3, 1))
    leg = _leg(bench, instructed=None, counter_account_id=bench.b)
    _wait(db_conn, leg)
    q = review_queue(db_conn)
    assert _sections(q) == {"pending_review": [], "needs_account": [], "waiting": [leg]}
    (unit,) = q.sections[2].units
    assert unit.waiting is not None and unit.needs_account is None
    assert (unit.waiting.account_id, unit.waiting.synced_through) == (bench.b, date(2026, 3, 1))


def test_a_waiting_account_never_fetched_has_no_synced_through(db_conn: Connection, bench: Bench) -> None:
    _sync(db_conn, bench.b, None)
    leg = _leg(bench, instructed=None, counter_account_id=bench.b)
    _wait(db_conn, leg)
    (unit,) = review_queue(db_conn).sections[2].units
    assert unit.waiting is not None and unit.waiting.synced_through is None


def test_the_sections_are_disjoint_needs_account_before_waiting(db_conn: Connection, bench: Bench) -> None:
    needs = _leg(bench)
    unrelated = bench.flow(bench.source(), done=False)
    waits = _leg(bench, instructed=None, counter_account_id=bench.b)
    _wait(db_conn, waits)
    both_leg = _leg(bench, on=date(2026, 3, 12))
    _wait(db_conn, both_leg)  # one leg that needs an account and carries the flag: needs_account wins
    q = review_queue(db_conn)
    assert _sections(q) == {
        "pending_review": [unrelated],
        "needs_account": [needs, both_leg],
        "waiting": [waits],
    }
    assert [s.total for s in q.sections] == [1, 2, 1] and q.total == 4


def test_a_confirmed_unit_is_in_no_section(db_conn: Connection, bench: Bench) -> None:
    bench.flow(bench.source())
    assert [s.total for s in review_queue(db_conn).sections] == [0, 0, 0]


def test_groups_count_units_per_currency_ordered_by_code_over_the_whole_section(
    db_conn: Connection, bench: Bench
) -> None:
    for i, cur in enumerate(["USD", "CHF", "USD", "USD", "GBP"]):
        _leg(bench, instructed=cur, on=date(2026, 1, 1 + i))
    _leg(bench, instructed="CHF", on=date(2026, 2, 1))
    q = review_queue(db_conn, limit=2)
    needs = q.sections[1]
    assert len(needs.units) == 2 and needs.total == 6 and needs.next_cursor
    assert [(g.currency, g.count) for g in needs.groups] == [("CHF", 2), ("GBP", 1), ("USD", 3)]
    assert q.sections[0].groups == () and q.sections[2].groups == ()
    only = review_queue(db_conn, section="needs_account", limit=2, cursor=needs.next_cursor)
    assert [(g.currency, g.count) for g in only.sections[0].groups] == [("CHF", 2), ("GBP", 1), ("USD", 3)]


def test_section_filter_and_cursor_stay_inside_the_section(db_conn: Connection, bench: Bench) -> None:
    legs = [_leg(bench, on=date(2026, 1, 1 + i)) for i in range(5)]
    flow = bench.flow(bench.source(on=date(2026, 1, 2)), done=False)
    first = review_queue(db_conn, section="needs_account", limit=2)
    assert [s.kind for s in first.sections] == ["needs_account"] and first.total == 6
    assert _sections(first)["needs_account"] == legs[:2] and first.sections[0].total == 5
    # between pages: one listed leg gets its account, a new needing leg arrives before the cursor
    db_conn.execute(
        text("UPDATE ledger_entry SET counter_account_id = :b WHERE id = :i"), {"b": bench.b, "i": legs[1]}
    )
    _leg(bench, on=date(2026, 1, 1))
    second = review_queue(db_conn, section="needs_account", limit=2, cursor=first.sections[0].next_cursor)
    assert _sections(second)["needs_account"] == legs[2:4] and second.sections[0].total == 5
    third = review_queue(db_conn, section="needs_account", limit=2, cursor=second.sections[0].next_cursor)
    assert _sections(third)["needs_account"] == legs[4:] and third.sections[0].next_cursor is None
    assert flow in _sections(review_queue(db_conn))["pending_review"]
    past = review_queue(db_conn, section="waiting", cursor=first.sections[0].next_cursor)
    assert past.sections[0].units == () and past.sections[0].total == 0


def test_the_count_is_pending_review_and_needs_account_never_waiting(
    db_conn: Connection, bench: Bench
) -> None:
    assert actionable_count(db_conn) == 0
    _leg(bench)  # needs an account
    waits = _leg(bench, instructed=None, counter_account_id=bench.b)
    _wait(db_conn, waits)
    assert actionable_count(db_conn) == 1  # a waiting unit is not counted
    bench.flow(bench.source(), done=False)  # pending review
    assert actionable_count(db_conn) == 2
    queue = _sections(review_queue(db_conn))
    assert actionable_count(db_conn) == len(queue["pending_review"]) + len(queue["needs_account"])
