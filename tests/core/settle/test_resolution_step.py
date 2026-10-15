"""Settle step 1: resolution wired into settling (spec §5.9, I18, I20, I37; architecture §5.2)."""

from __future__ import annotations

import importlib
import json
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.accounts import update_account
from app.core.ingest.identity import canonical_text
from app.core.resolution.registry import unconfigure_classifiers
from app.core.settle import settle
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import make_category, make_entry, make_run

settle_module = importlib.import_module("app.core.settle.settle")
resolution_module = importlib.import_module("app.core.settle.resolution")

MakeAccount = Callable[..., int]
DAY = date(2026, 2, 10)


def _src(conn: Connection, acct: int, *, run: int | None = None, **cols: Any) -> int:
    run = run or make_run(conn, acct)
    values: dict[str, Any] = {
        "importer": "test",
        "import_run_id": run,
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


def _new(conn: Connection, acct: int, **cols: Any) -> int:
    """A new, uninterpreted entry of a new source transaction (as ingest leaves it)."""
    src = _src(conn, acct, **cols)
    return make_entry(conn, src, type=None)


def _confirmed(
    conn: Connection, acct: int, *, name: str, category: int, payee: int | None, **cols: Any
) -> int:
    """A confirmed flow: values with `user` keys, a vote for history."""
    src = _src(conn, acct, counterparty_name=name, **cols)
    d: dict[str, Any] = {"type": {"pass": "user"}, "category": {"pass": "user"}}
    if payee:
        d["payee"] = {"pass": "user"}
    return make_entry(conn, src, category_id=category, payee_id=payee, derivation=json.dumps(d))


def _payee(conn: Connection, name: str) -> int:
    return int(
        conn.execute(text("INSERT INTO payee (name) VALUES (:n) RETURNING id"), {"n": name}).scalar_one()
    )


def _row(engine: Engine, entry: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT type, payee_id, category_id, counter_account_id, derivation, review_flags, version"
                " FROM ledger_entry WHERE id = :i"
            ),
            {"i": entry},
        ).one()


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


def test_pass0_makes_a_transfer_with_standing_own_account_keys(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        a = make_account(conn, name="Giro")
        b = make_account(conn, name="Card", external_ref=canonical_text("DE02 1234"))
        e = _new(conn, a, counterparty_ref="DE02 1234")
    assert settle(isolated_engine).error is None
    r = _row(isolated_engine, e)
    assert (r.type, r.counter_account_id, r.payee_id, r.category_id) == ("transfer", b, None, None)
    assert r.derivation == {
        "type": {"pass": "own_account", "basis": {"account_id": b}},
        "counter_account": {"pass": "own_account", "basis": {"account_id": b}},
    }
    assert r.version == 1


def test_a_rule_resolves_a_confirmed_flow_with_no_flags(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        p, c = _payee(conn, "Rewe"), make_category(conn, "Food")
        rp = rs.rule(conn, "rewe payee", "payee", p, conditions=(rs.name_is("REWE"),))
        rc = rs.rule(conn, "rewe cat", "category", c, conditions=(rs.name_is("REWE"),))
        e = _new(conn, acct, counterparty_name="REWE")
    assert settle(isolated_engine).error is None
    r = _row(isolated_engine, e)
    assert (r.type, r.payee_id, r.category_id, r.review_flags) == ("flow", p, c, [])
    assert r.derivation == {
        "type": {"pass": "rule", "basis": {"rule_id": rp}},
        "payee": {"pass": "rule", "basis": {"rule_id": rp}},
        "category": {"pass": "rule", "basis": {"rule_id": rc}},
    }
    assert r.version == 1


def test_a_flow_without_a_category_stays_unclassified(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        p = _payee(conn, "Rewe")
        rs.rule(conn, "rewe payee", "payee", p, conditions=(rs.name_is("REWE"),))
        e = _new(conn, acct, counterparty_name="REWE")
    settle(isolated_engine)
    assert _row(isolated_engine, e).review_flags == ["unclassified"]


def test_a_payee_condition_reads_the_payee_resolved_in_the_same_resolution(
    isolated_engine: Engine, acct: int
) -> None:
    with isolated_engine.begin() as conn:
        p, other, c = _payee(conn, "Rewe"), _payee(conn, "Other"), make_category(conn, "Food")
        rp = rs.rule(conn, "rewe payee", "payee", p, conditions=(rs.name_is("REWE"),))
        rc = rs.rule(conn, "cat", "category", c, conditions=(rs.payee_is(p), rs.name_is("REWE")))
        dangling = rs.rule(conn, "gone", "category", c, conditions=(rs.payee_is(other + 1000),))
        e = _new(conn, acct, counterparty_name="REWE")
        unrelated = _new(conn, acct, counterparty_name="ELSE")
    assert settle(isolated_engine).error is None
    r = _row(isolated_engine, e)
    assert (r.type, r.payee_id, r.category_id) == ("flow", p, c)
    assert r.derivation["category"] == {"pass": "rule", "basis": {"rule_id": rc}}
    assert r.derivation["type"] == {"pass": "rule", "basis": {"rule_id": rp}}  # the payee rule decides it
    assert _row(isolated_engine, unrelated).category_id is None
    assert dangling != rc


def _history_world(conn: Connection, acct: int, n: int = 3) -> tuple[int, int, int]:
    p, c = _payee(conn, "Edeka"), make_category(conn, "Food")
    for i in range(n):
        _confirmed(conn, acct, name="EDEKA Markt", category=c, payee=p, booked_on=date(2026, 1, 1 + i))
    return p, c, _new(conn, acct, counterparty_name="EDEKA Markt")


def test_history_proposes_with_unconfirmed_and_basis(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        p, c, e = _history_world(conn, acct)
    assert settle(isolated_engine).error is None
    r = _row(isolated_engine, e)
    assert (r.type, r.payee_id, r.category_id, r.review_flags) == ("flow", p, c, ["unconfirmed"])
    basis = {"matched_on": "counterparty_name+booking_text", "agree": 3, "of": 3, "since": "2026-01-01"}
    assert r.derivation["category"] == {"pass": "history", "basis": basis}
    assert r.derivation["type"]["pass"] == "history" and r.derivation["payee"]["pass"] == "history"


def test_second_settle_touches_nothing_and_no_version_moves(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        _, _, e = _history_world(conn, acct)
    first = settle(isolated_engine)
    assert e in first.touched_entry_ids
    before = _row(isolated_engine, e)
    assert settle(isolated_engine).touched_entry_ids == ()
    assert _row(isolated_engine, e) == before and before.version == 1


def test_standing_values_survive_a_rule_deleted_and_history_growing(
    isolated_engine: Engine, acct: int
) -> None:
    with isolated_engine.begin() as conn:
        p, c, e = _history_world(conn, acct)
        other = _payee(conn, "Other")
        rule = rs.rule(conn, "edeka payee", "payee", other, conditions=(rs.name_is("EDEKA Markt"),))
    settle(isolated_engine)
    r = _row(isolated_engine, e)
    assert r.payee_id == other and r.derivation["payee"]["pass"] == "rule"
    assert r.derivation["category"]["pass"] == "history"
    with isolated_engine.begin() as conn:
        conn.execute(text("DELETE FROM rule WHERE id = :i"), {"i": rule})
        for i in range(5):  # history now disagrees on the payee
            _confirmed(
                conn, acct, name="EDEKA Markt", category=c, payee=None, booked_on=date(2026, 1, 10 + i)
            )
    settle(isolated_engine)
    after = _row(isolated_engine, e)
    assert after.payee_id == other and after.derivation["payee"] == r.derivation["payee"]
    assert after.derivation["category"]["pass"] == "history"


def test_a_confirmed_entry_is_never_touched(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        c, c2 = make_category(conn, "Food"), make_category(conn, "Other")
        rs.rule(conn, "any", "category", c2, conditions=(rs.name_is("EDEKA Markt"),))
        reviewed = _confirmed(conn, acct, name="EDEKA Markt", category=c, payee=None)
        keyless = make_entry(conn, _src(conn, acct, counterparty_name="EDEKA Markt"), category_id=c)
    before = [_row(isolated_engine, i) for i in (reviewed, keyless)]
    assert settle(isolated_engine).touched_entry_ids == ()
    assert [_row(isolated_engine, i) for i in (reviewed, keyless)] == before


def test_a_proposal_is_rederived_after_another_entry_confirms(isolated_engine: Engine, acct: int) -> None:
    """A is confirmed by a rule in round 1; its vote gives B a proposal in round 2; round 3 never runs."""
    with isolated_engine.begin() as conn:
        p, c = _payee(conn, "Alpha"), make_category(conn, "Food")
        rs.rule(conn, "alpha payee", "payee", p, conditions=(rs.name_is("Alpha Shop"),))
        rs.rule(conn, "alpha cat", "category", c, conditions=(rs.name_is("Alpha Shop"),))
        a = _new(conn, acct, counterparty_name="Alpha Shop", counterparty_ref="REF-ALPHA")
        b = _new(conn, acct, counterparty_name="Some other text", counterparty_ref="REF-ALPHA")
    calls: list[int] = []
    real = resolution_module.resolve_step

    def counting(conn: Connection) -> Any:
        calls.append(1)
        return real(conn)

    settle_module.register_step("resolve", counting)
    try:
        assert settle(isolated_engine).error is None
    finally:
        settle_module.register_step("resolve", real)
    assert len(calls) == 2
    rb = _row(isolated_engine, b)
    assert (rb.type, rb.payee_id, rb.category_id) == ("flow", p, c)
    assert rb.derivation["category"]["pass"] == "history"
    assert rb.derivation["category"]["basis"]["of"] == 1
    assert _row(isolated_engine, a).review_flags == []
    assert rb.review_flags == ["unconfirmed"]


def test_history_snapshot_is_loaded_once_per_settle(
    isolated_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    with isolated_engine.begin() as conn:
        p, c = _payee(conn, "Alpha"), make_category(conn, "Food")
        rs.rule(conn, "alpha payee", "payee", p, conditions=(rs.name_is("Alpha Shop"),))
        rs.rule(conn, "alpha cat", "category", c, conditions=(rs.name_is("Alpha Shop"),))
        for i in range(4):
            _new(conn, acct, counterparty_name="Alpha Shop", counterparty_ref=f"R{i}")
        _new(conn, acct, counterparty_name="Beta")
    loads: list[int] = []
    real = resolution_module.load_snapshot
    monkeypatch.setattr(resolution_module, "load_snapshot", lambda conn: (loads.append(1), real(conn))[1])
    assert settle(isolated_engine).error is None
    assert loads == [1]


def test_an_account_reference_change_resettles(isolated_engine: Engine, make_account: MakeAccount) -> None:
    with isolated_engine.begin() as conn:
        a = make_account(conn, name="Giro")
        b = make_account(conn, name="Card")
        e = _new(conn, a, counterparty_ref="DE99 0000")
    settle(isolated_engine)
    assert _row(isolated_engine, e).type is None
    result = update_account(isolated_engine, b, external_ref="DE99 0000")
    assert result.error is None and e in result.touched_entry_ids
    r = _row(isolated_engine, e)
    assert (r.type, r.counter_account_id) == ("transfer", b)


def test_an_unconfigured_process_fails_loudly(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        _new(conn, acct)
    unconfigure_classifiers()
    result = settle(isolated_engine)
    assert result.error is not None and "ClassifiersNotConfigured" in result.error
    assert result.touched_entry_ids == ()


def test_a_split_has_one_transfer_at_most(isolated_engine: Engine, make_account: MakeAccount) -> None:
    with isolated_engine.begin() as conn:
        a = make_account(conn, name="Giro")
        b = make_account(conn, name="Card", external_ref=canonical_text("DE55"))
        src = _src(conn, a, counterparty_ref="DE55", amount=-1000)
        first = make_entry(conn, src, type=None, amount=-600)
        second = make_entry(conn, src, type=None, amount=-400)
    assert settle(isolated_engine).error is None
    assert (_row(isolated_engine, first).type, _row(isolated_engine, first).counter_account_id) == (
        "transfer",
        b,
    )
    assert _row(isolated_engine, second).type is None


def test_a_key_without_a_value_is_removed(isolated_engine: Engine, acct: int) -> None:
    with isolated_engine.begin() as conn:
        e = make_entry(
            conn,
            _src(conn, acct),
            type=None,
            derivation=json.dumps({"category": {"pass": "history", "basis": {}}, "document": {"pass": "x"}}),
        )
    settle(isolated_engine)
    assert _row(isolated_engine, e).derivation == {"document": {"pass": "x"}}


def test_a_value_without_a_key_is_kept(isolated_engine: Engine, acct: int) -> None:
    """A legacy value with no key is treated as a user's: a rule that would say otherwise loses."""
    with isolated_engine.begin() as conn:
        c = make_category(conn, "Food")
        rs.rule(conn, "r", "category", make_category(conn, "Other"), conditions=(rs.name_is("X"),))
        e = make_entry(
            conn,
            _src(conn, acct, counterparty_name="X"),
            category_id=c,
            derivation=json.dumps({"payee": {"pass": "history"}}),  # unconfirmed, so it is resolved
        )
    settle(isolated_engine)
    after = _row(isolated_engine, e)
    assert after.category_id == c
    assert "payee" not in after.derivation  # the key of a field without a value goes
