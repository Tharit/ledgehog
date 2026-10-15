"""`waiting` and `unmatched_transfer` (spec §5.7, §6): the SQL of the flags step, scenario by scenario, and
pinned to the pure predicates of `core/matching/states.py` over generated cases."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, text

from app.core.matching import Leg, unmatched, waiting
from app.core.settle.flags import recompute_review_flags
from app.core.settle.window import matching_window_days
from tests.invariants.helpers import (
    link_account,
    make_entry,
    make_instance,
    make_run,
    make_source,
    pair,
    scalar,
)

MakeAccount = Callable[..., int]
DAY = date(2026, 2, 10)
W = 7


def _flags(conn: Connection, entry: int) -> list[str]:
    return list(scalar(conn, "SELECT review_flags FROM ledger_entry WHERE id = :i", i=entry))


def _leg(conn: Connection, account: int, counter: int | None, *, on: date = DAY, amount: int = -1000) -> int:
    return make_entry(
        conn,
        make_source(conn, account, amount=amount, booked_on=on),
        type="transfer",
        counter_account_id=counter,
    )


def _synced(conn: Connection, account: int, through: date | None, *, closed_on: date | None = None) -> None:
    instance = make_instance(conn)
    link_account(conn, account, instance)
    if through is not None:
        make_run(conn, account, covered_through=through, instance_id=instance)
    if closed_on is not None:
        conn.execute(text("UPDATE account SET closed_on = :d WHERE id = :a"), {"d": closed_on, "a": account})


@pytest.fixture
def two(db_conn: Connection, make_account: MakeAccount) -> tuple[int, int]:
    return make_account(db_conn, name="A"), make_account(db_conn, name="C")


def _flag(conn: Connection, leg: int) -> list[str]:
    recompute_review_flags(conn)
    return _flags(conn, leg)


def test_the_window_is_the_connections(db_conn: Connection) -> None:
    assert matching_window_days(db_conn) == W


def test_a_counter_account_never_fetched_waits(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, None)
    assert _flag(db_conn, _leg(db_conn, a, c)) == ["waiting"]


@pytest.mark.parametrize(
    ("through", "expected"),
    [
        (DAY + timedelta(days=W - 1), ["waiting"]),
        (
            DAY + timedelta(days=W),
            ["unmatched_transfer"],
        ),  # synced through booked_on + window: nothing more is due
        (DAY + timedelta(days=W + 30), ["unmatched_transfer"]),
        (DAY - timedelta(days=400), ["waiting"]),  # a long way behind
    ],
)
def test_waiting_ends_when_the_counter_account_synced_through_the_window(
    db_conn: Connection, two: tuple[int, int], through: date, expected: list[str]
) -> None:
    a, c = two
    _synced(db_conn, c, through)
    assert _flag(db_conn, _leg(db_conn, a, c)) == expected


def test_a_leg_before_the_accounts_history_is_unmatched(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, DAY + timedelta(days=200))  # synced far past the leg: it can no longer arrive
    assert _flag(db_conn, _leg(db_conn, a, c, on=DAY - timedelta(days=100))) == ["unmatched_transfer"]


def test_an_unsynced_counter_account_is_unmatched(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    assert _flag(db_conn, _leg(db_conn, a, c)) == ["unmatched_transfer"]


def test_a_closed_counter_account_is_unmatched(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, None, closed_on=DAY + timedelta(days=500))
    assert _flag(db_conn, _leg(db_conn, a, c)) == ["unmatched_transfer"]


def test_an_unlinked_instance_makes_the_leg_unmatched(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, None)
    leg = _leg(db_conn, a, c)
    assert _flag(db_conn, leg) == ["waiting"]
    db_conn.execute(text("DELETE FROM account_source WHERE account_id = :a"), {"a": c})
    assert _flag(db_conn, leg) == ["unmatched_transfer"]


def test_a_leg_without_a_counter_account_is_unmatched(db_conn: Connection, two: tuple[int, int]) -> None:
    a, _ = two
    assert _flag(db_conn, _leg(db_conn, a, None)) == ["unmatched_transfer"]


def test_a_paired_leg_has_neither_and_a_flow_neither(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, None)
    x, y = _leg(db_conn, a, c), _leg(db_conn, c, a, amount=1000)
    pair(db_conn, x, y)
    flow = make_entry(db_conn, make_source(db_conn, a), type="flow")
    recompute_review_flags(db_conn)
    assert _flags(db_conn, x) == _flags(db_conn, y) == []
    assert "waiting" not in _flags(db_conn, flow) and "unmatched_transfer" not in _flags(db_conn, flow)


def test_a_second_run_touches_nothing(db_conn: Connection, two: tuple[int, int]) -> None:
    a, c = two
    _synced(db_conn, c, None)
    leg = _leg(db_conn, a, c)
    assert recompute_review_flags(db_conn) == [leg]
    assert recompute_review_flags(db_conn) == []


# ---- the SQL equals the pure predicates ----------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_sql_equals_the_pure_states_over_generated_legs(
    db_conn: Connection, make_account: MakeAccount, seed: int
) -> None:
    rng = random.Random(seed)
    window = rng.choice([0, 3, 7])
    db_conn.execute(text("SELECT set_config('ledger.matching_window_days', :w, true)"), {"w": str(window)})
    home = make_account(db_conn, name="Home")
    counters: list[int] = []
    for n in range(8):  # eight kinds of counter-account: unsynced, closed, never fetched, through some day
        c = make_account(db_conn, name=f"C{n}")
        counters.append(c)
        kind = n % 4
        if kind == 1:
            _synced(db_conn, c, None)
        elif kind == 2:
            _synced(db_conn, c, DAY + timedelta(days=rng.randint(-5, 15)))
        elif kind == 3:
            _synced(
                db_conn, c, DAY + timedelta(days=rng.randint(-5, 15)), closed_on=DAY + timedelta(days=900)
            )
    cases: list[tuple[int, Leg, bool]] = []
    for _ in range(120):
        counter = rng.choice([None, *counters])
        on = DAY + timedelta(days=rng.randint(-3, 12))
        paired = counter is not None and rng.random() < 0.2
        entry = _leg(db_conn, home, counter, on=on)
        if paired:
            assert counter is not None
            partner = make_entry(
                db_conn,
                make_source(
                    db_conn,
                    counter,
                    amount=1000,
                    booked_on=on,
                    run_id=make_run(db_conn, counter, status="failed"),  # a run that covers nothing
                ),
                type="transfer",
                counter_account_id=home,
            )
            pair(db_conn, entry, partner)
        cases.append(
            (
                entry,
                Leg(
                    entry_id=entry,
                    account_id=home,
                    currency="EUR",
                    amount=-1000,
                    booked_on=on,
                    counter_account_id=counter,
                ),
                paired,
            )
        )
    recompute_review_flags(db_conn)
    seen: set[tuple[bool, bool]] = set()
    for entry, leg, paired in cases:
        synced, through = False, None
        if leg.counter_account_id is not None:
            facts = db_conn.execute(
                text(
                    "SELECT s.synced, c.synced_through FROM v_account_synced s"
                    " JOIN v_account_coverage c USING (account_id) WHERE s.account_id = :a"
                ),
                {"a": leg.counter_account_id},
            ).one()
            synced, through = facts.synced, facts.synced_through
        w = waiting(leg, counter_synced=synced, synced_through=through, window=window) and not paired
        u = unmatched(leg, paired=paired, counter_synced=synced, synced_through=through, window=window)
        flags = _flags(db_conn, entry)
        assert ("waiting" in flags) == w, (leg, synced, through, paired)
        assert ("unmatched_transfer" in flags) == u, (leg, synced, through, paired)
        seen.add((w, u))
    assert seen == {(True, False), (False, True), (False, False)}  # every state occurs
