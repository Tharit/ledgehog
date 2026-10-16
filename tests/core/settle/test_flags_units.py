"""`unconfirmed` is judged per unit (spec §6): over a source and a transfer pair."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text

from app.core.resolution.confirmed import load_confirmed_ids, units_binds, units_sql
from app.core.settle.flags import recompute_review_flags
from tests.core.ingest.conftest import ledger  # noqa: F401  (fixture)
from tests.core.ingest.dup_helpers import Ledger
from tests.core.units.helpers import Bench, keys
from tests.fixtures import ledger_seed as seed


def test_a_transfer_partner_of_an_unconfirmed_leg_is_unconfirmed_too(ledger: Ledger) -> None:  # noqa: F811
    _, a, _, b = ledger.transfer_pair()
    history = {"category": {"pass": "history", "basis": {"from": "similar"}}}
    pair_key = ledger.one("SELECT derivation FROM ledger_entry WHERE id = :i", i=a).derivation
    ledger.tx(
        lambda c: c.execute(
            text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({**pair_key, **history}), "i": a},
        )
    )
    # the flags alone: a settle would rederive the pair's legs, and a category key on a transfer has no value
    ledger.tx(recompute_review_flags)
    flags = {r.id: list(r.review_flags) for r in ledger.q("SELECT id, review_flags FROM ledger_entry")}
    assert "unconfirmed" in flags[a]
    assert "unconfirmed" in flags[b]


# ---- flags per unit (spec §6): the unit CTE, in the database ------------------------------------


def _flags(conn: Connection, *ids: int) -> list[list[str]]:
    return [
        list(conn.execute(text("SELECT review_flags FROM ledger_entry WHERE id = :i"), {"i": i}).scalar_one())
        for i in ids
    ]


def _unit(conn: Connection, entry: int) -> Any:
    return conn.execute(
        text(f"WITH units AS ({units_sql()}) SELECT * FROM units WHERE id = :i"),
        {**units_binds(), "i": entry},
    ).one()


def test_a_proposal_marks_every_entry_of_its_split(db_conn: Connection, make_account: Any) -> None:
    b = Bench(db_conn, make_account)
    src = b.source()
    proposed = b.flow(src, derivation=keys(category="history"))
    sibling = b.flow(src)
    other = b.flow(b.source())
    recompute_review_flags(db_conn)
    assert _flags(db_conn, proposed, sibling, other) == [["unconfirmed"], ["unconfirmed"], []]


def test_an_unclassified_sibling_does_not_mark_the_complete_one(
    db_conn: Connection, make_account: Any
) -> None:
    b = Bench(db_conn, make_account)
    src = b.source()
    ok, open_ = b.flow(src), b.flow(src, done=False)
    recompute_review_flags(db_conn)
    assert _flags(db_conn, ok, open_) == [[], ["unclassified"]]
    # ... but the unit is not confirmed, so both are in the queue's unit and neither is confirmed
    assert not _unit(db_conn, ok).unit_ok and not _unit(db_conn, open_).unit_ok
    assert load_confirmed_ids(db_conn) == set()


def test_an_unpaired_transfer_is_unmatched_and_not_confirmed(db_conn: Connection, make_account: Any) -> None:
    b = Bench(db_conn, make_account)
    leg = b.transfer(b.source())
    recompute_review_flags(db_conn)
    assert _flags(db_conn, leg) == [["unmatched_transfer"]]  # no counter-account: nothing to wait for
    assert not _unit(db_conn, leg).unit_ok


def test_a_pair_is_one_unit_under_the_lower_source(db_conn: Connection, make_account: Any) -> None:
    b = Bench(db_conn, make_account)
    s1, s2 = b.source(), b.source(b.b)
    x, y, sib = b.transfer(s2), b.transfer(s1), b.flow(s2)
    b.pair(x, y)
    unit = {i: _unit(db_conn, i) for i in (x, y, sib)}
    assert {u.unit_key for u in unit.values()} == {s1}
    assert all(u.unit_ok for u in unit.values())
    assert load_confirmed_ids(db_conn) == {x, y, sib}
    assert unit[x].first_id == min(x, sib) and unit[y].first_id == y  # first_id stays per source (I31)


def test_a_sibling_of_an_unconfirmed_pair_is_unconfirmed_with_it(
    db_conn: Connection, make_account: Any
) -> None:
    b = Bench(db_conn, make_account)
    s1, s2 = b.source(), b.source(b.b)
    x, y = b.transfer(s1, derivation=keys(counter_account="history")), b.transfer(s2)
    sib_far = b.flow(s2)  # a sibling of the OTHER leg: reaches the proposal only through the pair
    b.pair(x, y)
    recompute_review_flags(db_conn)
    assert _flags(db_conn, x, y, sib_far) == [["unconfirmed"]] * 3
    assert recompute_review_flags(db_conn) == []  # idempotent


def test_derived_entries_are_in_no_unit(db_conn: Connection, make_account: Any) -> None:
    b = Bench(db_conn, make_account)
    d = seed.derived(db_conn, b.a)
    recompute_review_flags(db_conn)
    assert _flags(db_conn, d) == [[]]
    assert (
        db_conn.execute(
            text(f"WITH units AS ({units_sql()}) SELECT count(*) FROM units WHERE id = :i"),
            {**units_binds(), "i": d},
        ).scalar_one()
        == 0
    )
