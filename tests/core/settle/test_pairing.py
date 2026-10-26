"""Settle step 4: transfer pairing (spec §5.7, §5.9; I10, I18, I20, I22, I33, I37; architecture §5.2).

Real commits (`isolated_engine`): the deferred pair trigger (I10) fires at each commit, so every pair
these tests make has been accepted by the schema. Window: the configured 7 days.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.ingest.identity import canonical_text
from app.core.integrity import check_integrity
from app.core.resolution.confirmed import load_confirmed_ids
from app.core.settle import settle
from tests.invariants.helpers import make_entry, make_run, pair

MakeAccount = Callable[..., int]
DAY = date(2026, 2, 10)
PAIR = {"pass": "matcher_decision", "basis": {}}
PAIR_COUNTER = {"pass": "matcher_decision", "basis": {"from": "counterpart"}}

IBAN_A, IBAN_B, IBAN_C = "DE02 1111", "DE02 2222", "DE02 3333"


def src(conn: Connection, acct: int, **cols: Any) -> int:
    values: dict[str, Any] = {
        "origin": "import",
        "importer": "test",
        "import_run_id": make_run(conn, acct),
        "account_id": acct,
        "source_id": uuid.uuid4().hex,
        "source_format": "csv",
        "amount": -1000,
        "currency": "EUR",
        "booked_on": DAY,
        "raw": "{}",
    }
    values.update(cols)
    names = ", ".join(values)
    marks = ", ".join(f"CAST(:{c} AS jsonb)" if c == "raw" else f":{c}" for c in values)
    return int(
        conn.execute(
            text(f"INSERT INTO source_transaction ({names}) VALUES ({marks}) RETURNING id"),  # noqa: S608
            values,
        ).scalar_one()
    )


def new(conn: Connection, acct: int, amount: int, on: date = DAY, **cols: Any) -> int:
    """An uninterpreted entry, as ingest leaves it."""
    return make_entry(conn, src(conn, acct, amount=amount, booked_on=on, **cols), type=None)


def leg(
    conn: Connection,
    acct: int,
    amount: int,
    on: date = DAY,
    *,
    counter: int | None = None,
    keys: dict[str, Any] | None = None,
    **cols: Any,
) -> int:
    """A transfer leg the user decided: type (and counter-account) with `user` keys, unpaired."""
    derivation: dict[str, Any] = {"type": {"pass": "user"}}
    if counter is not None:
        derivation["counter_account"] = {"pass": "user"}
    derivation.update(keys or {})
    return make_entry(
        conn,
        src(conn, acct, amount=amount, booked_on=on, **cols),
        type="transfer",
        counter_account_id=counter,
        derivation=json.dumps(derivation),
    )


def row(engine: Engine, entry: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT type, counter_account_id, counterpart_entry_id, derivation, review_flags, version"
                " FROM ledger_entry WHERE id = :i"
            ),
            {"i": entry},
        ).one()


def settled(engine: Engine) -> Any:
    result = settle(engine)
    assert result.error is None, result.error
    return result


def partner_of(engine: Engine, entry: int) -> int | None:
    return row(engine, entry).counterpart_entry_id  # type: ignore[no-any-return]


def assert_integrity(engine: Engine) -> None:
    with engine.connect() as conn:
        report = check_integrity(conn)
    assert report.ok, {k: c.rows for k, c in report.checks.items() if c.rows}


@pytest.fixture
def accts(isolated_engine: Engine, make_account: MakeAccount) -> tuple[int, int, int]:
    with isolated_engine.begin() as conn:
        return (
            make_account(conn, name="Giro", external_ref=canonical_text(IBAN_A)),
            make_account(conn, name="Card", external_ref=canonical_text(IBAN_B)),
            make_account(conn, name="Other", external_ref=canonical_text(IBAN_C)),
        )


# ---- pass 0 and ingest order -----------------------------------------------------------------------


def test_pass0_legs_pair_and_the_unit_confirms(isolated_engine: Engine, accts: tuple[int, int, int]) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x = new(conn, a, -5000, counterparty_ref=IBAN_B)
        y = new(conn, b, 5000, on=DAY + timedelta(days=3), counterparty_ref=IBAN_A)
    result = settled(isolated_engine)
    rx, ry = row(isolated_engine, x), row(isolated_engine, y)
    assert (rx.counterpart_entry_id, ry.counterpart_entry_id) == (y, x)
    assert (rx.counter_account_id, ry.counter_account_id) == (b, a)
    # pass 0 gave both counter-accounts: the pair sets none, and writes only its own key
    assert rx.derivation["counterpart"] == ry.derivation["counterpart"] == PAIR
    assert rx.derivation["counter_account"]["pass"] == "own_account"
    assert rx.review_flags == ry.review_flags == []
    assert {x, y} <= set(result.touched_entry_ids)
    with isolated_engine.connect() as conn:
        assert {x, y} <= load_confirmed_ids(conn)
    assert_integrity(isolated_engine)


@pytest.mark.parametrize("a_first", [True, False])
def test_either_ingest_order_pairs_the_same(
    isolated_engine: Engine, accts: tuple[int, int, int], a_first: bool
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        first = new(
            conn,
            a if a_first else b,
            -5000 if a_first else 5000,
            counterparty_ref=IBAN_B if a_first else IBAN_A,
        )
    settled(isolated_engine)
    assert partner_of(isolated_engine, first) is None
    assert row(isolated_engine, first).review_flags == [
        "unmatched_transfer"
    ]  # B unsynced: nothing to wait for
    with isolated_engine.begin() as conn:
        second = new(
            conn,
            b if a_first else a,
            5000 if a_first else -5000,
            on=DAY + timedelta(days=1),
            counterparty_ref=IBAN_A if a_first else IBAN_B,
        )
    settled(isolated_engine)
    assert partner_of(isolated_engine, first) == second
    assert partner_of(isolated_engine, second) == first
    assert row(isolated_engine, first).review_flags == row(isolated_engine, second).review_flags == []
    assert_integrity(isolated_engine)


# ---- the keys a pair writes ---------------------------------------------------------------------------


def test_the_pair_sets_the_counter_account_and_its_key_only_on_a_leg_that_had_none(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=b)  # decided: a counter-account of its own
        y = leg(conn, b, 5000)  # typed, no counter-account yet
    settled(isolated_engine)
    rx, ry = row(isolated_engine, x), row(isolated_engine, y)
    assert (rx.counterpart_entry_id, ry.counterpart_entry_id) == (y, x)
    assert (rx.counter_account_id, ry.counter_account_id) == (b, a)
    assert rx.derivation == {
        "type": {"pass": "user"},
        "counter_account": {"pass": "user"},
        "counterpart": PAIR,
    }
    assert ry.derivation == {
        "type": {"pass": "user"},
        "counter_account": PAIR_COUNTER,
        "counterpart": PAIR,
    }
    assert row(isolated_engine, x).type == row(isolated_engine, y).type == "transfer"
    # both keys standing: the unit is confirmed with no review
    assert rx.review_flags == ry.review_flags == []
    assert_integrity(isolated_engine)


def test_neither_leg_knowing_its_counter_account_is_never_paired(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x, y = leg(conn, a, -5000), leg(conn, b, 5000)
    settled(isolated_engine)
    assert partner_of(isolated_engine, x) is None and partner_of(isolated_engine, y) is None
    assert row(isolated_engine, x).review_flags == ["unmatched_transfer"]


def test_a_guessed_counter_account_makes_the_pair_but_the_unit_stays_unconfirmed(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        for day in range(1, 4):  # history backs the guess
            _voter(conn, a, b, "Rent", DAY - timedelta(days=day * 10))
        x = leg(
            conn,
            a,
            -5000,
            counter=b,
            keys={"counter_account": {"pass": "history", "basis": {}}},
            counterparty_name="Rent",
        )
        y = leg(conn, b, 5000)
    settled(isolated_engine)
    rx, ry = row(isolated_engine, x), row(isolated_engine, y)
    assert rx.counterpart_entry_id == y and ry.counterpart_entry_id == x
    assert rx.derivation["counter_account"]["pass"] == "history"
    assert rx.review_flags == ry.review_flags == ["unconfirmed"]
    with isolated_engine.connect() as conn:
        assert not {x, y} & load_confirmed_ids(conn)


# ---- which candidate ----------------------------------------------------------------------------------


def test_a_pair_stands_when_a_better_candidate_arrives_later(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=b)
        far = leg(conn, b, 5000, on=DAY + timedelta(days=5))
    settled(isolated_engine)
    assert partner_of(isolated_engine, x) == far
    with isolated_engine.begin() as conn:
        near = leg(conn, b, 5000, on=DAY)  # would be the closest candidate, but x is taken
    result = settled(isolated_engine)
    assert partner_of(isolated_engine, x) == far and partner_of(isolated_engine, near) is None
    assert x not in result.touched_entry_ids


def test_three_legs_resolve_by_date_order(isolated_engine: Engine, accts: tuple[int, int, int]) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        # two equal outgoing legs on A, one incoming on B: the earlier booking gets it
        late = leg(conn, a, -5000, on=DAY + timedelta(days=2), counter=b)
        early = leg(conn, a, -5000, on=DAY, counter=b)
        incoming = leg(conn, b, 5000, on=DAY + timedelta(days=1))
    settled(isolated_engine)
    assert partner_of(isolated_engine, incoming) == early
    assert partner_of(isolated_engine, late) is None


def test_cross_currency_pairs_by_the_instructed_amount(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        eur = make_account(conn, name="Giro")
        usd = make_account(conn, name="Travel", currency="USD")
        x = leg(
            conn, eur, -1000, counter=usd, instructed_amount=-1100, instructed_currency="USD"
        )  # a withdrawal abroad: dollars
        y = leg(conn, usd, 1100, currency="USD")
    settled(isolated_engine)
    assert partner_of(isolated_engine, x) == y and partner_of(isolated_engine, y) == x
    assert row(isolated_engine, y).counter_account_id == eur
    assert_integrity(isolated_engine)


@pytest.mark.parametrize(("days", "pairs"), [(7, True), (8, False), (-7, True), (-8, False)])
def test_window_edges(isolated_engine: Engine, accts: tuple[int, int, int], days: int, pairs: bool) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=b)
        y = leg(conn, b, 5000, on=DAY + timedelta(days=days))
    settled(isolated_engine)
    assert (partner_of(isolated_engine, x) == y) is pairs


def test_a_counter_account_elsewhere_blocks_the_pair(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, c = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=c)
        y = leg(conn, b, 5000)
    settled(isolated_engine)
    assert partner_of(isolated_engine, x) is None and partner_of(isolated_engine, y) is None


# ---- idempotence, versions, I20 ------------------------------------------------------------------------


def test_a_second_settle_pairs_nothing_and_moves_no_version(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, c = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=b)
        y = leg(conn, b, 5000)
        z = leg(conn, a, -777, counter=c)  # stays unpaired
    settled(isolated_engine)
    before = {e: row(isolated_engine, e) for e in (x, y, z)}
    assert before[x].version == before[y].version == 2  # the counterpart link is structural: it bumps
    assert before[z].version == 1
    again = settled(isolated_engine)
    assert again.touched_entry_ids == ()
    assert {e: row(isolated_engine, e) for e in (x, y, z)} == before


def test_an_unpaired_transfer_is_never_confirmed(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x = leg(conn, a, -5000, counter=b)
    settled(isolated_engine)
    with isolated_engine.connect() as conn:
        assert x not in load_confirmed_ids(conn)


# ---- a pair falls with a changed guess (I18) --------------------------------------------------------------


def _voter(conn: Connection, a: int, b: int, name: str, on: date) -> None:
    """A confirmed pair a -> b of `name`: a vote for history (counter-accounts need a pair)."""
    keys = json.dumps(
        {"type": {"pass": "user"}, "counter_account": {"pass": "user"}, "counterpart": {"pass": "user"}}
    )
    x = make_entry(
        conn,
        src(conn, a, amount=-4200, booked_on=on, counterparty_name=name),
        type="transfer",
        derivation=keys,
        counter_account_id=b,
    )
    y = make_entry(
        conn, src(conn, b, amount=4200, booked_on=on), type="transfer", derivation=keys, counter_account_id=a
    )
    pair(conn, x, y)


def _stale_pair(conn: Connection, a: int, b: int, name: str) -> tuple[int, int]:
    """A pair whose leg on `a` holds a history guess of `b` (stored), paired with a leg on `b`."""
    x = make_entry(
        conn,
        src(conn, a, amount=-5000, counterparty_name=name),
        type="transfer",
        counter_account_id=b,
        derivation=json.dumps(
            {
                "type": {"pass": "history", "basis": {}},
                "counter_account": {"pass": "history", "basis": {}},
                "counterpart": PAIR,
            }
        ),
    )
    y = make_entry(
        conn,
        src(conn, b, amount=5000),
        type="transfer",
        counter_account_id=a,
        derivation=json.dumps(
            {"type": {"pass": "user"}, "counter_account": PAIR_COUNTER, "counterpart": PAIR}
        ),
    )
    pair(conn, x, y)
    return x, y


def test_a_pair_falls_with_a_changed_guess_and_forms_again_elsewhere(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, c = accts
    with isolated_engine.begin() as conn:
        for day in range(1, 4):  # history says: "Rent" goes to C
            _voter(conn, a, c, "Rent", DAY - timedelta(days=day * 10))
        x, p = _stale_pair(conn, a, b, "Rent")  # the stored pair still follows an old guess of B
        q = leg(conn, c, 5000)  # the partner history points at
    settled(isolated_engine)
    rx, rp, rq = row(isolated_engine, x), row(isolated_engine, p), row(isolated_engine, q)
    assert rx.counter_account_id == c and rx.counterpart_entry_id == q and rq.counterpart_entry_id == x
    assert rx.derivation["counter_account"]["pass"] == "history"
    assert rx.derivation["counterpart"] == PAIR
    # the old partner is released: the counter-account and key its pair set are gone, the rest is kept
    assert rp.counterpart_entry_id is None and rp.counter_account_id is None
    assert {k: v["pass"] for k, v in rp.derivation.items()} == {"type": "user"}
    assert rp.review_flags == ["unmatched_transfer"]
    assert rq.counter_account_id == a and rq.derivation["counter_account"] == PAIR_COUNTER
    assert_integrity(isolated_engine)
    again = settled(isolated_engine)
    assert again.touched_entry_ids == ()


def test_a_pair_falls_when_the_guess_goes_away_and_the_leg_waits_unpaired(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        x, p = _stale_pair(conn, a, b, "Nobody knows")  # no votes: history proposes nothing
    settled(isolated_engine)
    rx, rp = row(isolated_engine, x), row(isolated_engine, p)
    assert rx.counterpart_entry_id is None and rp.counterpart_entry_id is None
    assert rx.counter_account_id is None and "counter_account" not in rx.derivation
    assert "counterpart" not in rx.derivation and "counterpart" not in rp.derivation
    assert rp.counter_account_id is None
    assert settled(isolated_engine).touched_entry_ids == ()


def test_a_stable_guess_keeps_the_pair(isolated_engine: Engine, accts: tuple[int, int, int]) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        for day in range(1, 4):  # history agrees with the stored guess
            _voter(conn, a, b, "Rent", DAY - timedelta(days=day * 10))
        x, p = _stale_pair(conn, a, b, "Rent")
    settled(isolated_engine)
    assert partner_of(isolated_engine, x) == p and partner_of(isolated_engine, p) == x
    rx = row(isolated_engine, x)
    assert rx.counter_account_id == b and rx.review_flags == ["unconfirmed"]
    assert row(isolated_engine, p).counter_account_id == a
    assert settled(isolated_engine).touched_entry_ids == ()


# ---- rounds: pairs teach history -------------------------------------------------------------------


def test_a_pair_a_settle_made_teaches_history_in_the_next_round(
    isolated_engine: Engine, accts: tuple[int, int, int]
) -> None:
    a, b, _ = accts
    with isolated_engine.begin() as conn:
        for day in (1, 2):
            new(
                conn,
                a,
                -9000 - day,
                on=DAY - timedelta(days=day * 3),
                counterparty_ref=IBAN_B,
                counterparty_name="Mietkonto",
            )
            new(conn, b, 9000 + day, on=DAY - timedelta(days=day * 3), counterparty_ref=IBAN_A)
        # no IBAN: only what history learned from the pairs above can type it
        z = new(conn, a, -777, counterparty_name="Mietkonto")
    settled(isolated_engine)
    rz = row(isolated_engine, z)
    assert rz.type == "transfer" and rz.counter_account_id == b
    assert rz.derivation["counter_account"]["pass"] == "history"
