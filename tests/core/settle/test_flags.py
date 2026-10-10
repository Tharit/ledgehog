"""Review flags (spec §6, I23): rewritten wholesale by one set-based statement."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from app.core.settle.flags import recompute_review_flags
from tests.invariants.helpers import make_category, make_entry, make_movement, make_source, scalar, seed_clean

MakeAccount = Callable[..., int]


def _flags(conn: Connection, entry: int) -> list[str]:
    return list(scalar(conn, "SELECT review_flags FROM ledger_entry WHERE id = :i", i=entry))


def _derive(conn: Connection, entry: int, derivation: dict[str, object]) -> None:
    conn.execute(
        text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"),
        {"d": json.dumps(derivation), "i": entry},
    )


@pytest.fixture
def acct(db_conn: Connection, make_account: MakeAccount) -> int:
    return make_account(db_conn)


def test_new_entry_without_type_is_unclassified(db_conn: Connection, acct: int) -> None:
    src = make_source(db_conn, acct)
    e = make_entry(db_conn, src, type=None)
    assert recompute_review_flags(db_conn) == [e]
    assert _flags(db_conn, e) == ["unclassified"]


def test_flow_without_category_is_unclassified(db_conn: Connection, acct: int) -> None:
    _, e = make_movement(db_conn, acct)
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == ["unclassified"]


def test_categorised_flow_with_no_keys_is_clean(db_conn: Connection, acct: int) -> None:
    cat = make_category(db_conn, "Food")
    src = make_source(db_conn, acct)
    e = make_entry(db_conn, src, category_id=cat)
    assert recompute_review_flags(db_conn) == []
    assert _flags(db_conn, e) == []


def test_transfer_is_not_unclassified(db_conn: Connection, acct: int, make_account: MakeAccount) -> None:
    other = make_account(db_conn, name="Other")
    e = make_entry(db_conn, make_source(db_conn, acct), type="transfer", counter_account_id=other)
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == []


@pytest.mark.parametrize("pass_name", ["history", "llm", "matcher_proposal"])
def test_proposal_key_makes_the_entry_unconfirmed(db_conn: Connection, acct: int, pass_name: str) -> None:
    cat = make_category(db_conn, "Food")
    e = make_entry(db_conn, make_source(db_conn, acct), category_id=cat)
    _derive(db_conn, e, {"category": {"pass": pass_name}})
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == ["unconfirmed"]


@pytest.mark.parametrize("pass_name", ["own_account", "rule", "matcher_decision", "user"])
def test_standing_keys_do_not_hold_up_review(db_conn: Connection, acct: int, pass_name: str) -> None:
    cat = make_category(db_conn, "Food")
    e = make_entry(db_conn, make_source(db_conn, acct), category_id=cat)
    _derive(db_conn, e, {"category": {"pass": pass_name}})
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == []


def test_unclassified_and_unconfirmed_are_stored_sorted(db_conn: Connection, acct: int) -> None:
    _, e = make_movement(db_conn, acct)
    _derive(db_conn, e, {"type": {"pass": "history"}, "payee": {"pass": "rule"}})
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == ["unclassified", "unconfirmed"]


def test_one_standing_among_proposal_keys_still_unconfirmed(db_conn: Connection, acct: int) -> None:
    cat = make_category(db_conn, "Food")
    e = make_entry(db_conn, make_source(db_conn, acct), category_id=cat)
    _derive(db_conn, e, {"payee": {"pass": "user"}, "category": {"pass": "llm"}})
    recompute_review_flags(db_conn)
    assert _flags(db_conn, e) == ["unconfirmed"]


def test_derived_entries_never_get_flags(db_conn: Connection, make_account: MakeAccount) -> None:
    c = seed_clean(db_conn, make_account)
    for derived in (c.opening, c.reconciliation, c.valuation):
        _derive(db_conn, derived, {"type": {"pass": "history"}})
    recompute_review_flags(db_conn)
    for derived in (c.opening, c.reconciliation, c.valuation):
        assert _flags(db_conn, derived) == []


def test_flags_are_rewritten_wholesale_a_stale_flag_goes(db_conn: Connection, acct: int) -> None:
    cat = make_category(db_conn, "Food")
    e = make_entry(db_conn, make_source(db_conn, acct), category_id=cat)
    db_conn.execute(
        text("UPDATE ledger_entry SET review_flags = ARRAY['waiting','unmatched_transfer'] WHERE id = :i"),
        {"i": e},
    )
    assert recompute_review_flags(db_conn) == [e]
    assert _flags(db_conn, e) == []


def test_second_run_touches_nothing_and_keeps_versions(db_conn: Connection, acct: int) -> None:
    _, e = make_movement(db_conn, acct)
    assert recompute_review_flags(db_conn) == [e]
    version = scalar(db_conn, "SELECT version FROM ledger_entry WHERE id = :i", i=e)
    assert recompute_review_flags(db_conn) == []
    assert scalar(db_conn, "SELECT version FROM ledger_entry WHERE id = :i", i=e) == version


def test_empty_database(db_conn: Connection) -> None:
    assert recompute_review_flags(db_conn) == []
